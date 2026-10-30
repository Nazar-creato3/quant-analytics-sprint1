"""CPU PPO (FinRL algorithm family, MIT). No ElegantRL/GPU required."""
from __future__ import annotations

import math
import random
from typing import Sequence

_ACTIONS = 3
_FEE = 0.0005
_H = 8  # hidden


def _closes(prices: Sequence[float]) -> list[float]:
    return [float(p) for p in prices if p is not None and float(p) > 0]


def _obs(close: list[float], i: int, pos: int) -> list[float]:
    r5 = close[i] / close[i - 5] - 1.0 if i >= 5 else 0.0
    r20 = close[i] / close[i - 20] - 1.0 if i >= 20 else r5
    if i >= 10:
        rets = [close[j] / close[j - 1] - 1.0 for j in range(i - 9, i + 1)]
        mean = sum(rets) / len(rets)
        var = sum((x - mean) ** 2 for x in rets) / max(len(rets) - 1, 1)
        vol = math.sqrt(var)
    else:
        vol = 0.01
    return [r5, r20, vol, float(pos) / 2.0]


def _matmul(w: list[list[float]], x: list[float]) -> list[float]:
    return [sum(a * b for a, b in zip(row, x)) for row in w]


def _relu(x: list[float]) -> list[float]:
    return [v if v > 0 else 0.0 for v in x]


def _softmax(logits: list[float]) -> list[float]:
    m = max(logits)
    exps = [math.exp(v - m) for v in logits]
    s = sum(exps) or 1.0
    return [e / s for e in exps]


def _init_net(rng: random.Random, n_in: int, n_out: int) -> dict[str, list]:
    scale = 0.25
    return {
        "w1": [[rng.uniform(-scale, scale) for _ in range(n_in)] for _ in range(_H)],
        "b1": [0.0] * _H,
        "w2": [[rng.uniform(-scale, scale) for _ in range(_H)] for _ in range(n_out)],
        "b2": [0.0] * n_out,
    }


def _forward(net: dict[str, list], x: list[float]) -> list[float]:
    h = _relu([s + b for s, b in zip(_matmul(net["w1"], x), net["b1"])])
    return [s + b for s, b in zip(_matmul(net["w2"], h), net["b2"])]


def _add_in_place(net: dict[str, list], grad: dict[str, list], lr: float) -> None:
    for key in net:
        if key.startswith("w"):
            for i, row in enumerate(net[key]):
                for j in range(len(row)):
                    row[j] += lr * grad[key][i][j]
        else:
            for i in range(len(net[key])):
                net[key][i] += lr * grad[key][i]


def _zero_like(net: dict[str, list]) -> dict[str, list]:
    out: dict[str, list] = {}
    for key, val in net.items():
        if key.startswith("w"):
            out[key] = [[0.0] * len(row) for row in val]
        else:
            out[key] = [0.0] * len(val)
    return out


def train_ppo(
    prices: Sequence[float],
    *,
    episodes: int = 8,
    seed: int = 7,
) -> dict:
    close = _closes(prices)
    if len(close) < 32:
        raise ValueError("need_at_least_32_closes")
    rng = random.Random(seed)
    actor = _init_net(rng, 4, _ACTIONS)
    critic = _init_net(rng, 4, 1)
    clip = 0.2
    gamma = 0.97
    lr = 0.02
    episodes = max(3, min(int(episodes), 16))

    for _ in range(episodes):
        pos = 0
        batch: list[tuple[list[float], int, float, float]] = []
        for i in range(20, len(close) - 1):
            x = _obs(close, i, pos)
            probs = _softmax(_forward(actor, x))
            r = rng.random()
            cum = 0.0
            action = _ACTIONS - 1
            for a, p in enumerate(probs):
                cum += p
                if r <= cum:
                    action = a
                    break
            ret = close[i + 1] / close[i] - 1.0
            sign = 1 if action == 1 else (-1 if action == 2 else 0)
            reward = sign * ret - _FEE * abs(action - pos)
            value = _forward(critic, x)[0]
            batch.append((x, action, reward, max(probs[action], 1e-6)))
            pos = action
            _ = value

        # GAE-lite: discounted returns
        g = 0.0
        returns: list[float] = []
        for *_rest, reward, _old in reversed([(0, 0, b[2], b[3]) for b in batch]):
            g = reward + gamma * g
            returns.append(g)
        returns.reverse()
        mean_r = sum(returns) / len(returns)
        var_r = sum((v - mean_r) ** 2 for v in returns) / max(len(returns) - 1, 1)
        std_r = math.sqrt(var_r) or 1.0
        adv = [(v - mean_r) / std_r for v in returns]

        for epoch in range(3):
            g_actor = _zero_like(actor)
            g_critic = _zero_like(critic)
            for (x, action, _rw, old_p), a, ret in zip(batch, adv, returns):
                probs = _softmax(_forward(actor, x))
                ratio = probs[action] / old_p
                clipped = min(max(ratio, 1.0 - clip), 1.0 + clip)
                pg = a if ratio * a <= clipped * a else 0.0
                # score-function hint on logits
                logits = _forward(actor, x)
                for k in range(_ACTIONS):
                    indicator = 1.0 if k == action else 0.0
                    logits[k] += lr * 0.15 * pg * (indicator - probs[k])
                # write logits back via last layer nudge
                h = _relu([s + b for s, b in zip(_matmul(actor["w1"], x), actor["b1"])])
                for k in range(_ACTIONS):
                    delta = 0.08 * pg * ((1.0 if k == action else 0.0) - probs[k])
                    actor["b2"][k] += delta
                    for j, hj in enumerate(h):
                        actor["w2"][k][j] += delta * hj
                pred = _forward(critic, x)[0]
                err = ret - pred
                critic["b2"][0] += lr * 0.1 * err
                hc = _relu([s + b for s, b in zip(_matmul(critic["w1"], x), critic["b1"])])
                for j, hj in enumerate(hc):
                    critic["w2"][0][j] += lr * 0.1 * err * hj
            _ = g_actor, g_critic, epoch

    return {"actor": actor, "critic": critic}


def infer_ppo(prices: Sequence[float], actor: dict[str, list]) -> tuple[int, float]:
    close = _closes(prices)
    if len(close) < 21:
        return 0, 0.0
    x = _obs(close, len(close) - 1, 0)
    probs = _softmax(_forward(actor, x))
    action = int(max(range(_ACTIONS), key=lambda a: probs[a]))
    sign = 1 if action == 1 else (-1 if action == 2 else 0)
    return sign, float(probs[action] - 1.0 / _ACTIONS)
