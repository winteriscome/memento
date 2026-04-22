def _compare_versions(current: str, latest: str) -> int:
    def parse(v: str) -> tuple:
        v = v.lstrip("v")
        parts = []
        for p in v.split("."):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(p)
        return tuple(parts)

    c, l = parse(current), parse(latest)
    if c < l:
        return -1
    if c > l:
        return 1
    return 0

print(_compare_versions("0.8.0", "v0.9.0"))
print(_compare_versions("0.9.0", "v0.9.0"))
print(_compare_versions("0.10.0", "v0.9.0"))
