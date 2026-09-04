"""Classe les remplacants attitres apres les titulaires libres."""
import pathlib
p = pathlib.Path("engine.py"); s = p.read_text()
old = "    return sorted(pool, key=lambda p: (load.get(p.id, 0), planned.get(p.id, 0), p.name))"
new = '''    def rank(player):
        played = load.get(player.id, 0)
        scheduled = planned.get(player.id, 0)
        # A player with no dates of their own is a designated substitute:
        # asked only once every regular who is free that week has been asked.
        return (scheduled == 0, played, scheduled, player.name)

    return sorted(pool, key=rank)'''
if new in s and old not in s:
    print("deja fait")
elif s.count(old) != 1:
    print(f"ECHEC : {s.count(old)} occurrence(s)")
else:
    p.write_text(s.replace(old, new)); print("ok : remplacants attitres classes en dernier")
