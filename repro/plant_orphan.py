"""Plant a structural orphan in a COPY of a persisted Chroma segment: remove node X from every neighbour list at every layer.
usage: plant_orphan.py <src_store_dir> <dst_store_dir> <user_id>   (src is never modified; dst must not exist)
Everything is done with raw struct edits that follow the documented layout (hnswaudit/layout.py)."""
import os, shutil, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from hnswaudit import layout, safepickle

src, dst, uid = sys.argv[1], sys.argv[2], sys.argv[3]
shutil.copytree(src, dst)
seg = [d for d in os.listdir(dst) if os.path.isdir(os.path.join(dst, d))][0]
sd = os.path.join(dst, seg)
g = layout.load(sd)
o = safepickle.loads(open(os.path.join(sd, "index_metadata.pickle"), "rb").read())
st = o.state if hasattr(o, "state") else o
label = int(st["id_to_label"][uid])
X = int(np.nonzero(g.labels == label)[0][0])
assert X != g.entry, "refusing to orphan the entry point"
d0 = bytearray(open(os.path.join(sd, "data_level0.bin"), "rb").read())
removed0 = 0
for v in range(g.cur):
    base = v * g.stride
    flags = struct.unpack_from("<I", d0, base)[0]
    cnt = flags & 0xFFFF
    nb = list(struct.unpack_from(f"<{cnt}I", d0, base + 4)) if cnt else []
    if X in nb:
        nb = [x for x in nb if x != X]
        removed0 += 1
        struct.pack_into("<I", d0, base, (flags & ~0xFFFF) | len(nb))
        struct.pack_into(f"<{g.maxM0}I", d0, base + 4, *(nb + [0] * (g.maxM0 - len(nb))))
ll = bytearray(open(os.path.join(sd, "link_lists.bin"), "rb").read())
per = 4 + 4 * g.maxM
pos, removed_up = 0, 0
for v in range(g.cur):
    L = struct.unpack_from("<I", ll, pos)[0]
    for lvl in range(L // per):
        b = pos + 4 + lvl * per
        cnt = struct.unpack_from("<I", ll, b)[0] & 0xFFFF
        nb = list(struct.unpack_from(f"<{cnt}I", ll, b + 4)) if cnt else []
        if X in nb:
            nb = [x for x in nb if x != X]
            removed_up += 1
            struct.pack_into("<I", ll, b, len(nb))
            struct.pack_into(f"<{g.maxM}I", ll, b + 4, *(nb + [0] * (g.maxM - len(nb))))
    pos += 4 + L
open(os.path.join(sd, "data_level0.bin"), "wb").write(d0)
open(os.path.join(sd, "link_lists.bin"), "wb").write(ll)
print(f"planted: user id {uid} label {label} internal {X} level {int(g.levels[X])}; removed from {removed0} layer-0 lists, {removed_up} upper lists")
