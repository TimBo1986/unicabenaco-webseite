#!/usr/bin/env python3
# pruefe_wortlaut.py — steht freigegebene Copy genau so in der Seite?
#
# Rein lesend. Nutzung: tools/pruefe_wortlaut.py docs/specs/WEB3-faq.json
# Die Spec nennt eine Seite ("datei") und optional weitere ("weitere_seiten").
#
# Die Spec-Datei nennt eine Seite und je Sprache Schluessel mit ihrem Wortlaut.
# Geprueft wird: jeder Schluessel steht im Woerterbuch der Sprache genau mit
# diesem Wert, und das Markup traegt den DE-Wortlaut. Exit 0 = alles gleich.
import io, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pruefe_seite import SPRACHEN, woerterbuch  # noqa: E402


def pruefe(spec, s):
    fehler = []
    for lang in SPRACHEN:
        w = woerterbuch(s, lang)
        for k, soll in spec.get(lang, {}).items():
            ist = json.loads(w[k]) if k in w else None
            if ist != soll:
                fehler.append('%s.%s: %r statt %r' % (lang, k, (ist or '')[:50], soll[:50]))
    ohne = re.sub(r'<!--.*?-->', ' ', s, flags=re.S)
    for k, soll in spec.get('de', {}).items():
        m = re.search(r'<([a-z0-9]+)\b[^>]*\bdata-i18n="%s"[^>]*>(.*?)</\1>' % k, ohne, re.S)
        if not m or m.group(2) != soll:
            fehler.append('Markup %s: %r statt %r' % (k, (m.group(2) if m else '')[:50], soll[:50]))
    return fehler


def main():
    if len(sys.argv) < 2:
        print('Nutzung: tools/pruefe_wortlaut.py SPEC.json', file=sys.stderr)
        sys.exit(2)
    spec = json.load(io.open(sys.argv[1], encoding='utf-8'))
    # „datei“ mit den Sprachen auf oberster Ebene; dazu optional „weitere_seiten“: {datei: {de, it, en}}
    seiten = [(spec['datei'], spec)] + list(spec.get('weitere_seiten', {}).items())
    alle, stellen = [], 0
    for datei, teil in seiten:
        fehler = pruefe(teil, io.open(datei, encoding='utf-8').read())
        alle += ['%s: %s' % (datei, f) for f in fehler]
        stellen += sum(len(teil.get(l, {})) for l in SPRACHEN) + len(teil.get('de', {}))
    for f in alle:
        print('  FEHLER   ' + f)
    print(('FEHLGESCHLAGEN — %d von %d Stellen' % (len(alle), stellen)) if alle
          else 'OK — %d Seiten: %d Stellen (Woerterbuecher und Markup) wie freigegeben' % (len(seiten), stellen))
    sys.exit(1 if alle else 0)


if __name__ == '__main__':
    main()
