"""Symbolic pickle reader. NEVER imports, calls or instantiates anything.

``index_metadata.pickle`` is untrusted input. This is an opcode interpreter for the small
subset needed to read Chroma's id<->label map: containers, ints, floats, strings, bytes,
None/bool, memo, and *inert* class references (GLOBAL / STACK_GLOBAL / REDUCE / NEWOBJ /
BUILD produce ``Inert`` placeholder objects holding names and state, nothing is executed).
Any opcode outside the allow-list, any inert reference whose module.name is not in
``ALLOWED_REFS``, and any structural inconsistency raises ``PickleRefused``.
"""
import struct


class PickleRefused(Exception):
    pass


ALLOWED_REFS = {
    ("chromadb.segment.impl.vector.local_persistent_hnsw", "PersistentData"),
    ("builtins", "set"),
    ("builtins", "dict"),
    ("builtins", "list"),
    ("builtins", "tuple"),
    ("builtins", "frozenset"),
    ("copyreg", "_reconstructor"),
    ("builtins", "object"),
}


class Inert:
    """Placeholder for a class reference or an object built from one."""

    def __init__(self, module, name):
        self.module, self.name = module, name
        self.args = None
        self.state = None

    def __repr__(self):
        return f"Inert({self.module}.{self.name})"


_MARK = object()
MAX_ITEMS = 50_000_000


def loads(data, max_bytes=1 << 31):
    if len(data) > max_bytes:
        raise PickleRefused("pickle too large")
    stack, memo, i, n = [], {}, 0, len(data)
    metastack = []

    def pop_to_mark():
        if not metastack:
            raise PickleRefused("no mark")
        items = stack[:]
        base = metastack.pop()
        del stack[base:]
        return items[base:]

    def read(k):
        nonlocal i
        if i + k > n:
            raise PickleRefused("truncated")
        b = data[i:i + k]
        i += k
        return b

    def check_ref(m, nm):
        if (m, nm) not in ALLOWED_REFS:
            raise PickleRefused(f"disallowed class reference {m}.{nm}")
        return Inert(m, nm)

    while True:
        op = read(1)
        if op == b".":  # STOP
            if len(stack) != 1:
                raise PickleRefused("stack not a single value at STOP")
            return stack[0]
        if op == b"\x80":  # PROTO
            if read(1)[0] > 5:
                raise PickleRefused("unknown protocol")
        elif op == b"\x95":  # FRAME
            read(8)
        elif op == b"(":  # MARK
            metastack.append(len(stack))
        elif op == b"N":
            stack.append(None)
        elif op == b"\x88":
            stack.append(True)
        elif op == b"\x89":
            stack.append(False)
        elif op == b"K":
            stack.append(read(1)[0])
        elif op == b"M":
            stack.append(struct.unpack("<H", read(2))[0])
        elif op == b"J":
            stack.append(struct.unpack("<i", read(4))[0])
        elif op == b"\x8a":  # LONG1
            k = read(1)[0]
            stack.append(int.from_bytes(read(k), "little", signed=True))
        elif op == b"\x8b":  # LONG4
            k = struct.unpack("<I", read(4))[0]
            stack.append(int.from_bytes(read(k), "little", signed=True))
        elif op == b"G":
            stack.append(struct.unpack(">d", read(8))[0])
        elif op == b"\x8c":  # SHORT_BINUNICODE
            stack.append(read(read(1)[0]).decode("utf-8"))
        elif op == b"X":  # BINUNICODE
            stack.append(read(struct.unpack("<I", read(4))[0]).decode("utf-8"))
        elif op == b"\x8d":  # BINUNICODE8
            stack.append(read(struct.unpack("<Q", read(8))[0]).decode("utf-8"))
        elif op == b"C":  # SHORT_BINBYTES
            stack.append(bytes(read(read(1)[0])))
        elif op == b"B":  # BINBYTES
            stack.append(bytes(read(struct.unpack("<I", read(4))[0])))
        elif op == b"}":
            stack.append({})
        elif op == b"]":
            stack.append([])
        elif op == b")":
            stack.append(())
        elif op == b"\x8f":  # EMPTY_SET
            stack.append(set())
        elif op == b"\x94":  # MEMOIZE
            memo[len(memo)] = stack[-1]
        elif op == b"q":  # BINPUT
            memo[read(1)[0]] = stack[-1]
        elif op == b"r":  # LONG_BINPUT
            memo[struct.unpack("<I", read(4))[0]] = stack[-1]
        elif op == b"h":  # BINGET
            k = read(1)[0]
            if k not in memo:
                raise PickleRefused("bad memo get")
            stack.append(memo[k])
        elif op == b"j":
            k = struct.unpack("<I", read(4))[0]
            if k not in memo:
                raise PickleRefused("bad memo get")
            stack.append(memo[k])
        elif op == b"s":  # SETITEM
            v, k = stack.pop(), stack.pop()
            d = stack[-1]
            if not isinstance(d, dict):
                raise PickleRefused("SETITEM on non-dict")
            d[k] = v
        elif op == b"u":  # SETITEMS
            items = pop_to_mark()
            d = stack[-1]
            if not isinstance(d, dict) or len(items) % 2:
                raise PickleRefused("bad SETITEMS")
            for a in range(0, len(items), 2):
                d[items[a]] = items[a + 1]
        elif op == b"a":  # APPEND
            v = stack.pop()
            if not isinstance(stack[-1], list):
                raise PickleRefused("APPEND on non-list")
            stack[-1].append(v)
        elif op == b"e":  # APPENDS
            items = pop_to_mark()
            if not isinstance(stack[-1], list):
                raise PickleRefused("APPENDS on non-list")
            stack[-1].extend(items)
        elif op == b"\x90":  # ADDITEMS
            items = pop_to_mark()
            if not isinstance(stack[-1], set):
                raise PickleRefused("ADDITEMS on non-set")
            stack[-1].update(items)
        elif op == b"t":  # TUPLE
            stack.append(tuple(pop_to_mark()))
        elif op == b"\x85":
            stack.append((stack.pop(),))
        elif op == b"\x86":
            b, a = stack.pop(), stack.pop()
            stack.append((a, b))
        elif op == b"\x87":
            c, b, a = stack.pop(), stack.pop(), stack.pop()
            stack.append((a, b, c))
        elif op == b"\x93":  # STACK_GLOBAL
            nm, m = stack.pop(), stack.pop()
            stack.append(check_ref(m, nm))
        elif op == b"c":  # GLOBAL (text)
            m = b""
            while (ch := read(1)) != b"\n":
                m += ch
            nm = b""
            while (ch := read(1)) != b"\n":
                nm += ch
            stack.append(check_ref(m.decode(), nm.decode()))
        elif op == b"R":  # REDUCE: inert
            args, f = stack.pop(), stack.pop()
            if not isinstance(f, Inert):
                raise PickleRefused("REDUCE on non-reference")
            o = Inert(f.module, f.name)
            o.args = args
            stack.append(o)
        elif op == b"\x81":  # NEWOBJ: inert
            args, cls = stack.pop(), stack.pop()
            if not isinstance(cls, Inert):
                raise PickleRefused("NEWOBJ on non-reference")
            o = Inert(cls.module, cls.name)
            o.args = args
            stack.append(o)
        elif op == b"b":  # BUILD: inert state attach
            st, o = stack.pop(), stack[-1]
            if not isinstance(o, Inert):
                raise PickleRefused("BUILD on non-reference object")
            o.state = st
        elif op == b"0":  # POP
            stack.pop()
        elif op == b"2":  # DUP
            stack.append(stack[-1])
        else:
            raise PickleRefused(f"opcode {op!r} not in allow-list")
        if len(stack) > MAX_ITEMS:
            raise PickleRefused("stack too large")
