"""Fine-tune RapidOCR's PP-OCRv6 tiny recognizer on GTA 6 subtitle rows (same network = same speed), with an
English-only head: the 6 906-way output (Chinese, Japanese… included) becomes ~97-way, initialised from the original
weights of those characters, so it starts from what the model already knows and can no longer answer "ó" or "〇".

usage: egitim\\Scripts\\python.exe train_rec.py [--epochs N] [--check]
Writes models\\gta6_rec_tiny_en.onnx (+ .json report). Input / preprocessing exactly as RapidOCR: BGR, height 48,
width by the row's ratio (at least 320), (x/255 - 0.5) / 0.5, zero padding on the right.
"""
import argparse
import json
import math
import os
import random
import sys
import time

import cv2
import numpy as np
import onnx
import torch
import torch.nn as nn
from onnx2torch import convert

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ortak import DATA, TINY as _TINY  # noqa: E402

HERE = str(DATA)
TINY = str(_TINY)
ROWS = os.path.join(HERE, "rows")
OUTDIR = os.path.join(HERE, "models")
H = 48
# printable ASCII without space (RapidOCR adds blank + space itself) + the Turkish letters (PS5 menus and notices in
# Turkish: a line with them is not translated, which "goruntule" for "görüntüle" broke)
CHARS = [chr(c) for c in range(33, 127)] + list("çğıöşüÇĞİÖŞÜ")


# ---------------------------------------------------------------- model

def old_charset():
    m = onnx.load(TINY)
    meta = {p.key: p.value for p in m.metadata_props}
    return ["blank"] + meta["character"].split("\n") + [" "]


def build_model():
    """onnx2torch model with the softmax removed and the classifier cut to blank + CHARS + space."""
    net = convert(onnx.load(TINY))
    old = old_charset()
    keep = [0] + [old.index(c) for c in CHARS] + [len(old) - 1]
    g = net.graph
    # the classifier: the last module whose weight has the old number of classes
    head = None
    for name, mod in net.named_modules():
        for pname, p in mod.named_parameters(recurse=False):
            if len(old) in p.shape:
                head = (name, mod)
    if head is None:
        # MatMul with a constant weight: onnx2torch keeps the weight as a buffer / constant module
        for name, mod in net.named_modules():
            for bname, b in mod.named_buffers(recurse=False):
                if len(old) in b.shape:
                    head = (name, mod)
    name, mod = head
    for pname, p in list(mod.named_parameters(recurse=False)) + list(mod.named_buffers(recurse=False)):
        if len(old) not in p.shape:
            continue
        axis = list(p.shape).index(len(old))
        sliced = p.detach().index_select(axis, torch.tensor(keep))
        if isinstance(p, nn.Parameter):
            setattr(mod, pname, nn.Parameter(sliced.clone()))
        else:
            mod.register_buffer(pname, sliced.clone())
    if isinstance(mod, nn.Linear):
        mod.out_features = len(keep)
    # drop the final softmax: CTC is trained on log-probabilities
    for node in reversed(list(g.nodes)):
        if node.op == "call_module" and "softmax" in str(type(net.get_submodule(node.target))).lower() or \
                node.op == "call_function" and "softmax" in str(node.target).lower():
            node.replace_all_uses_with(node.args[0])
            g.erase_node(node)
            break
    net.recompile()
    return net, keep, head[0]


def set_train(net):
    """Training mode with the batch-norm statistics frozen (a few thousand rows of one game: the batch statistics
    would drift away from what the network learned on millions of pictures)."""
    net.train()
    for m in net.modules():
        if isinstance(m, nn.modules.batchnorm._BatchNorm) or "BatchNorm" in type(m).__name__:
            m.eval()


class Exported(nn.Module):
    """The trained network with the softmax put back (RapidOCR expects probabilities)."""

    def __init__(self, net):
        super().__init__()
        self.net = net

    def forward(self, x):
        return torch.softmax(self.net(x), dim=2)


# ---------------------------------------------------------------- data

def load_rows(path):
    return [json.loads(l) for l in open(path, encoding="utf-8")]


def augment(img, rng):
    img = img.astype(np.float32)
    if rng.random() < 0.8:                                   # brightness / contrast / colour cast (TV, HDR, PS5)
        img = img * rng.uniform(0.7, 1.2) + rng.uniform(-25, 25)
        img = img * np.array([rng.uniform(0.75, 1.15) for _ in range(3)], np.float32)
    if rng.random() < 0.3:                                   # gamma
        img = 255 * (np.clip(img, 0, 255) / 255) ** rng.uniform(0.8, 1.25)
    img = np.clip(img, 0, 255).astype(np.uint8)
    h, w = img.shape[:2]
    if rng.random() < 0.5:                                   # row cut a little differently (margins)
        t, b = rng.integers(-3, 4), rng.integers(-3, 4)
        img = cv2.copyMakeBorder(img, max(0, -t), max(0, -b), 0, 0, cv2.BORDER_REPLICATE)[max(0, t):, :]
        img = img[:img.shape[0] - max(0, b)] if b > 0 and img.shape[0] - b > 10 else img
    if rng.random() < 0.3:                                   # lower stream resolution (720p, 900p)
        f = rng.uniform(0.5, 0.85)
        small = cv2.resize(img, (max(8, int(w * f)), max(8, int(img.shape[0] * f))), interpolation=cv2.INTER_AREA)
        img = cv2.resize(small, (w, img.shape[0]), interpolation=cv2.INTER_LINEAR)
    if rng.random() < 0.25:
        img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.3, 0.9))
    if rng.random() < 0.4:                                   # stream / JPEG blocks
        ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(35, 95))])
        img = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    if rng.random() < 0.25:
        img = np.clip(img + rng.normal(0, rng.uniform(2, 7), img.shape), 0, 255).astype(np.uint8)
    if rng.random() < 0.6:                                   # a little wider / narrower: a pixel of width must not
        f = rng.uniform(0.94, 1.06)                          # drop a letter ("Goddamn it..." -> "Goddamn i...")
        img = cv2.resize(img, (max(8, int(round(img.shape[1] * f))), img.shape[0]), interpolation=cv2.INTER_LINEAR)
    return img


def to_tensor(img, width):
    """As RapidOCR does it: height 48, width by the ratio, cut to the batch width (int(), not rounded up)."""
    h, w = img.shape[:2]
    rw = int(math.ceil(H * w / h))
    rw = width if rw > width else rw
    x = cv2.resize(img, (rw, H)).astype(np.float32).transpose(2, 0, 1) / 255
    x = (x - 0.5) / 0.5
    out = np.zeros((3, H, width), np.float32)
    out[:, :, :rw] = x
    return out


def encode(label):
    idx = {c: i + 1 for i, c in enumerate(CHARS)}
    space = len(CHARS) + 1
    return [space if c == " " else idx[c] for c in label if c == " " or c in idx]


def batches(items, size, rng, shuffle=True):
    """Rows of similar width ratio together (little padding), batches in random order."""
    items = sorted(items, key=lambda r: r["ratio"])
    out = [items[i:i + size] for i in range(0, len(items), size)]
    if shuffle:
        out = [b for b in out if len(b) == size]          # one batch size too (same reason as the widths)
        rng.shuffle(out)
    return out


def make_batch(group, rng, train):
    imgs = []
    for r in group:
        img = cv2.imread(os.path.join(ROWS, r["id"]))
        imgs.append(augment(img, rng) if train else img)
    width = int(H * max(320 / H, max(i.shape[1] / i.shape[0] for i in imgs)))
    # few widths only: every new input size costs the GPU seconds of set-up the first time it is trained on; 32 px
    # steps keep the padding small (the app reads one row at a time, with no padding on the right: a model used to
    # wide grey padding made up letters at the end of the row, "The Forg" -> "The Forgott")
    if train:
        width = int(math.ceil(width / 32) * 32)
    x = torch.from_numpy(np.stack([to_tensor(i, width) for i in imgs]))
    targets = [encode(r["label"]) for r in group]
    return x, targets


# ---------------------------------------------------------------- decode / score

def decode(logits):
    """Greedy CTC -> texts (blank 0, space last)."""
    out = []
    for seq in logits.argmax(dim=2).cpu().numpy():
        prev, chars = -1, []
        for k in seq:
            if k != prev and k != 0:
                chars.append(" " if k == len(CHARS) + 1 else CHARS[k - 1])
            prev = k
        out.append("".join(chars))
    return out


def cer(pred, gold):
    import rapidfuzz.distance.Levenshtein as L
    return L.distance(pred, gold) / max(1, len(gold))


def evaluate(net, items, device, rng):
    """One row at a time, exactly as RapidOCR feeds it in the app (no padding beyond 320 px)."""
    net.eval()
    errs, exact, n = 0.0, 0, 0
    with torch.no_grad():
        for r in items:
            x, _ = make_batch([r], rng, False)
            p = decode(net(x.to(device)))[0]
            errs += cer(p, r["label"])
            exact += p == r["label"]
            n += 1
    set_train(net)
    return errs / max(1, n), exact / max(1, n)


# ---------------------------------------------------------------- main

def main():
    global ROWS
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=14)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--check", action="store_true", help="only build the model and compare it with the ONNX one")
    ap.add_argument("--labels", default="labels.jsonl")
    ap.add_argument("--smoke", type=int, default=0, help="stop after this many steps (a quick test)")
    ap.add_argument("--out", default="gta6_rec_tiny_en.onnx")
    ap.add_argument("--rows", default="rows", help="folder of the row pictures")
    args = ap.parse_args()
    ROWS = os.path.join(HERE, args.rows)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    net, keep, head = build_model()
    print("sınıflandırıcı:", head, "| sınıf:", len(keep), "| cihaz:", device, flush=True)
    if args.check:
        import onnxruntime as ort
        sess = ort.InferenceSession(TINY, providers=["CPUExecutionProvider"])
        img = cv2.imread(os.path.join(ROWS, sorted(os.listdir(ROWS))[0]))
        x = to_tensor(img, max(320, int(math.ceil(H * img.shape[1] / img.shape[0]))))[None]
        ref = sess.run(None, {"x": x})[0][:, :, keep]
        net.eval()
        got = torch.softmax(net(torch.from_numpy(x)), dim=2).detach().numpy()
        # the cut head renormalises over fewer classes; argmax over the kept classes must agree
        print("aynı karar oranı:", float((ref.argmax(2) == got.argmax(2)).mean()))
        print("eski:", decode(torch.from_numpy(np.log(ref + 1e-9)))[0], "| yeni:", decode(torch.from_numpy(got))[0])
        return
    rng = np.random.default_rng(7)
    random.seed(7)
    labels = load_rows(os.path.join(HERE, args.labels))
    gold = {g["id"]: g["label"] for g in json.load(open(os.path.join(HERE, "gold.json"), encoding="utf-8"))} \
        if os.path.exists(os.path.join(HERE, "gold.json")) else {}
    for r in labels:
        r["ratio"] = 1.0  # filled below
    meta = {}
    for line in open(os.path.join(HERE, "rows.jsonl"), encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        meta[r["id"]] = r
    for r in labels:
        b = r.get("box") or meta[r["id"]]["box"]
        r["ratio"] = (b[3] - b[2]) / max(1, b[1] - b[0])
    # nothing of the gold rows in training: not their groups (the same row in other pictures), not the same line
    # read elsewhere (another session)
    from rapidfuzz import fuzz
    by_id = {r["id"]: r for r in labels}
    gold_groups = {by_id[i]["group"] for i in gold if i in by_id}
    gold_texts = list(gold.values())
    train = [r for r in labels if r["group"] % 10 != 0 and r["agreement"] >= 85 and r["group"] not in gold_groups
             and not any(fuzz.ratio(r["label"], t) >= 90 for t in gold_texts)]
    val = [r for r in labels if r["group"] % 10 == 0 and r["agreement"] >= 92]
    gold_items = [dict(meta[i], label=t, ratio=(meta[i]["box"][3] - meta[i]["box"][2]) / max(1, meta[i]["h"]))
                  for i, t in gold.items()]
    print(f"eğitim {len(train)} satır, doğrulama {len(val)}, altın {len(gold_items)}", flush=True)
    net.to(device)
    set_train(net)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-4)
    steps = args.epochs * math.ceil(len(train) / args.batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=steps, pct_start=0.08)
    ctc = nn.CTCLoss(blank=0, zero_infinity=True)
    scaler = torch.amp.GradScaler(enabled=device == "cuda")
    base = evaluate(net, gold_items or val, device, rng)
    print(f"başlangıç (kesilmiş baş): CER {base[0]:.4f}, tam satır {base[1]:.3f}", flush=True)
    report = {"start": base, "epochs": []}
    best = (evaluate(net, val, device, rng)[0], None)
    t0 = time.time()
    for epoch in range(args.epochs):
        total = 0.0
        for group in batches(train, args.batch, rng):
            x, targets = make_batch(group, rng, True)
            x = x.to(device)
            with torch.autocast(device_type=device, enabled=device == "cuda"):
                logits = net(x)
            logp = logits.float().log_softmax(2).permute(1, 0, 2)        # T, B, C
            T = logp.shape[0]
            flat = torch.tensor([c for t in targets for c in t], dtype=torch.long)
            lens = torch.tensor([len(t) for t in targets], dtype=torch.long)
            loss = ctc(logp, flat, torch.full((len(targets),), T, dtype=torch.long), lens)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            nn.utils.clip_grad_norm_(net.parameters(), 5.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            total += float(loss)
            step = getattr(main, "step", 0) + 1
            main.step = step
            if args.smoke and step >= args.smoke:
                break
        v = evaluate(net, val, device, rng)
        gscore = evaluate(net, gold_items, device, rng) if gold_items else v
        report["epochs"].append({"epoch": epoch + 1, "loss": total, "val": v, "gold": gscore})
        print(f"tur {epoch + 1}: kayıp {total:.1f} | doğrulama CER {v[0]:.4f} tam {v[1]:.3f} | altın CER "
              f"{gscore[0]:.4f} tam {gscore[1]:.3f} | {time.time() - t0:.0f} sn", flush=True)
        # the best turn by the validation rows (the gold rows only measure: choosing by them would flatter them)
        if v[0] < best[0]:
            best = (v[0], {k: v_.detach().cpu().clone() for k, v_ in net.state_dict().items()})
    if best[1] is not None:
        net.load_state_dict(best[1])
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, args.out)
    net.to("cpu").eval()
    dummy = torch.zeros(1, 3, H, 640)
    torch.onnx.export(Exported(net), dummy, path, input_names=["x"], output_names=["out"],
                      dynamic_axes={"x": {0: "batch", 3: "width"}, "out": {0: "batch", 1: "steps"}}, opset_version=17,
                      dynamo=False)
    m = onnx.load(path)
    p = m.metadata_props.add()
    p.key, p.value = "character", "\n".join(CHARS)
    onnx.save(m, path)
    report["best_val_cer"] = best[0]
    json.dump(report, open(path.replace(".onnx", ".json"), "w"), indent=1)
    print("KAYDEDİLDİ:", path, flush=True)


if __name__ == "__main__":
    main()
