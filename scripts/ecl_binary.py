"""Minimal reader for the binary output formats (EGRID, INIT, UNRST).

Yields (name, count, type, values) per array, in file order, so a caller can see
the section structure -- which array follows which LGR header -- and not just a
dictionary of names.
"""
import struct

_ITEM = {'INTE': 4, 'REAL': 4, 'LOGI': 4, 'DOUB': 8, 'CHAR': 8, 'MESS': 0}


def records(path):
    with open(path, 'rb') as f:
        while True:
            head = f.read(4)
            if len(head) < 4:
                return
            n = struct.unpack('>i', head)[0]
            desc = f.read(n)
            f.read(4)
            name = desc[0:8].decode().strip()
            count = struct.unpack('>i', desc[8:12])[0]
            typ = desc[12:16].decode().strip()
            size = _ITEM.get(typ, 4)
            data = []
            left = count
            while left > 0:
                blk = f.read(4)
                if len(blk) < 4:
                    break
                m = struct.unpack('>i', blk)[0]
                chunk = f.read(m)
                f.read(4)
                k = m // size if size else 0
                if typ == 'DOUB':
                    data += list(struct.unpack('>%dd' % k, chunk))
                elif typ == 'REAL':
                    data += list(struct.unpack('>%df' % k, chunk))
                elif typ in ('INTE', 'LOGI'):
                    data += list(struct.unpack('>%di' % k, chunk))
                elif typ.startswith('C'):
                    data += [chunk[i * 8:(i + 1) * 8].decode('latin1') for i in range(k)]
                left -= k
                if k == 0:
                    break
            yield name, count, typ, data
