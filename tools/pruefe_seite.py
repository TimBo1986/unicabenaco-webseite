#!/usr/bin/env python3
# pruefe_seite.py — Abnahme-Gate fuer die Seiten dieses Repos
#
# Rein lesend. Idempotent. Schreibt nichts, aendert nichts.
#
# Nutzung:
#   tools/pruefe_seite.py [DATEI] [VERGLEICHSSTAND]
#   tools/pruefe_seite.py index.html main
#   tools/pruefe_seite.py --selftest
#   tools/pruefe_seite.py --help
#
# DATEI          Default: index.html
# VERGLEICHSSTAND  git-Referenz, gegen die geprueft wird. Default: HEAD.
#
# Exit 0 = keine Fehler. Exit 1 = mindestens ein Fehler.
# Hinweise sind Beobachtungen und lassen den Lauf gruen.
#
# ---------------------------------------------------------------------------
# Warum die Schluesselpruefung in BEIDE Richtungen laeuft
#
# Die erste Fassung kannte nur eine Richtung: "steht im DOM, fehlt im
# Woerterbuch". Beim Aufloesen des Saeulen-Abschnitts (Spec 0002) lief ein
# Loeschbereich versehentlich ueber einen ganzen Beat hinweg — der Abschnitt
# "Wir schreiben dazu, was wir nicht wissen" verschwand samt Ueberschrift,
# Fliesstext und Geraet. Alle verbliebenen DOM-Schluessel hatten weiterhin
# ihren Woerterbucheintrag, also meldete der Pruefer gruen, waehrend ein
# ganzer Abschnitt fehlte. Ein Gate, das nur eine Richtung kennt, ist von
# einem gruenen Gate nicht zu unterscheiden.
#
# Seither gilt: ein Schluessel, der im Vergleichsstand im DOM stand und jetzt
# nicht mehr, ist ein FEHLER — es sei denn, er ist im Woerterbuch mit einem
# Kommentar als ausgesetzt vermerkt. Aussetzen ist eine Entscheidung und
# gehoert aufgeschrieben; stilles Verschwinden ist ein Versehen.
#
# Derselbe Fehler hat auf Anhieb eine zweite Luecke aufgedeckt: ls_eyebrow und
# ls_h2, die Ueberschrift des aufgeloesten Abschnitts, waren ebenfalls ohne
# Vermerk weg.
# ---------------------------------------------------------------------------

import io, json, os, re, subprocess, sys

SPRACHEN = ('de', 'it', 'en')

# Bewusst in allen Sprachen identisch — kein Uebersetzungsrest.
GLEICH_OK = {'ex_eyebrow', 'c_role', 'l_role', 't_role', 'wl_name',
             'foot_left', 'wl_mail', 'orte_label', 'm0_q', 'm4_q',
             'mi_vlabel', 'mi_mlabel'}

# Externe Verweise, die es geben darf. Alles andere ist ein neuer Request.
# www.lagonord.it kam am 7.9.2026 dazu: die Fusszeilen-Signatur zeigt seither
# dorthin. Die drei .de-Eintraege bleiben stehen, sie werden weiter gebraucht —
# sie stecken in auskommentierten Vorfassungen, und Punkt 6 liest die ganze
# Datei, Kommentare eingeschlossen.
BEKANNT = {'https://www.lagonord.it',
           'https://www.lagonord.de', 'https://www.lagonord.de/privacy.html',
           'https://www.lagonord.de/imprint.html', 'https://unicabenaco.com',
           'https://unicabenaco.com/assets/og.jpg',
           'https://www.instagram.com/luna_the_digital_dog/',
           # Seit 22.11.2026: app.html wird erst seitdem gelesen (siehe
           # woerterbuch). Alle drei standen dort schon vorher:
           # die canonical-Zeile der Seite selbst,
           'https://unicabenaco.com/app',
           # und die beiden Platzhalter im auskommentierten Block „ZUM LAUNCH:
           # Store-Links" — Punkt 6 liest Kommentare mit. Beim Start werden
           # sie durch die echten Store-Adressen ersetzt und hier nachgezogen.
           'https://apps.apple.com/app/idXXXXXXXX',
           'https://play.google.com/store/apps/details?id=XXX',
           # Ebenso seit 22.11.2026 lesbar, beide standen vorher schon dort:
           # canonical-Zeilen von partner.html und confirmed.html,
           'https://unicabenaco.com/partner', 'https://unicabenaco.com/confirmed',
           # und der WhatsApp-Knopf der Partnerseite; die Adresse wird im
           # Skript aus "https://wa.me/" + Nummer + Text zusammengesetzt.
           'https://wa.me/'}

# Bilder, die schon vor Spec 0001 ohne loading="lazy" dastanden.
VORBESTAND = {'assets/app/onboarding_wer.jpg', 'assets/cristina.jpg',
              'assets/tim.jpg', 'assets/luna.jpg',
              # Seit 22.11.2026: Kopfbild von app.html, steht über der Falz und
              # soll nicht lazy laden. Die Falz kennt der Pruefer nur in
              # index.html ('<!-- 2 · PROBLEM'); in app.html gilt alles als
              # unterhalb.
              '/assets/app/oggi_greeting.jpg'}


def usage():
    print(''.join(l[2:] if l.startswith('# ') else l[1:]
                  for l in io.open(__file__, encoding='utf-8')
                  .read().split('\n\n')[0].splitlines(True)[1:]))
    sys.exit(0)


# WEB3 (Leitstand 26.11.2026 22:45): Markup und DE-Woerterbuch wortgleich. Diese fuenf
# Schluessel in partner.html weichen schon vor WEB3 ab (etwa „Max 8“ im Markup,
# „Max. 8“ im Woerterbuch); gemeldet in WEB3, partner.html wird dort nicht
# geaendert. Bis zur Entscheidung Hinweis statt Fehler.
MARKUP_ALTBESTAND = {('partner.html', 'pr_p'), ('partner.html', 'pe_max8'),
                     ('partner.html', 'pe_max10'), ('partner.html', 'pe_max12'),
                     ('partner.html', 'pf_meta')}


def woerterbuch_roh(quelle, lang):
    """Der Quelltext eines Sprachblocks, Kommentare eingeschlossen."""
    m = re.search(r'\n( +)%s:\{\n(.*?)\n\1},?\n\1[a-z]{2}:\{|\n( +)%s:\{\n(.*?)\n\3}\n};'
                  % (lang, lang), quelle, re.S)
    return (m.group(2) or m.group(4)) if m else ''


def live_schluessel(blob):
    """Die Schluessel, die im Browser wirklich gelten — in Reihenfolge, Doppelte
    eingeschlossen. Zeichenketten und Kommentare werden vorher entfernt: eine
    auskommentierte Vorfassung (CLAUDE.md: „die alte Fassung auskommentiert
    direkt darunter“) ist kein Schluessel, und ein „x:“ in einem Text auch nicht.
    """
    aus, i, n = [], 0, len(blob)
    while i < n:
        c = blob[i]
        if c in '"\'`':
            j = i + 1
            while j < n and blob[j] != c:
                j += 2 if blob[j] == '\\' else 1
            aus.append(' '); i = j + 1
        elif blob.startswith('/*', i):
            j = blob.find('*/', i + 2); i = n if j < 0 else j + 2; aus.append(' ')
        elif blob.startswith('//', i):
            j = blob.find('\n', i); i = n if j < 0 else j; aus.append(' ')
        else:
            aus.append(c); i += 1
    return re.findall(r'(?:^|[,{]|\s)([a-z_0-9]+)\s*:', ''.join(aus), re.M)


def woerterbuch(quelle, lang):
    """Ein Sprachblock als {schluessel: "wert mit Anfuehrungszeichen"}.

    Schluessel stehen mehrere pro Zeile, Werte duerfen Kommas und maskierte
    Anfuehrungszeichen enthalten — darum Token fuer Token statt zeilenweise.
    """
    # Einrueckung beliebig, aber innerhalb eines Blocks gleich (\1, \3):
    # index.html und partner.html ruecken mit einem Leerzeichen ein, app.html
    # und confirmed.html mit zweien. Bis 22.11.2026 kannte der Pruefer nur ein
    # Leerzeichen und fand dort kein Woerterbuch — app.html war also nie grün.
    blob = woerterbuch_roh(quelle, lang)
    return dict(re.findall(r'(?:^|[,{]\s*)\s*([a-z_0-9]+):("(?:[^"\\]|\\.)*")',
                           blob, re.M))


def dom_schluessel(quelle):
    """Nur sichtbares Markup. Auskommentiertes ist Notiz, kein DOM.

    -alt kam am 7.9.2026 dazu. Seither liegen die App-Aufnahmen je Sprache
    getrennt, und die Alt-Texte sind mit ihnen ins Woerterbuch gezogen. Ohne
    diesen Zweig stuenden zehn Schluessel im DOM, die der Pruefer nicht sieht —
    in keiner der beiden Richtungen. Ein Gate, das die Haelfte der Attribute
    nicht kennt, ist von einem gruenen Gate nicht zu unterscheiden.
    """
    ohne = re.sub(r'<!--.*?-->', ' ', quelle, flags=re.S)
    return set(re.findall(r'data-i18n(?:-ph|-alt)?="([a-z_0-9]+)"', ohne))


def pruefe(s, alt, mit_bildern=True, datei_name='index.html'):
    """Gibt (fehler, hinweise) zurueck. s = Datei jetzt, alt = Vergleichsstand."""
    fehler, hinweise = [], []
    sichtbar = re.sub(r'<!--.*?-->', lambda c: ' ' * len(c.group(0)), s, flags=re.S)

    # 1 · Inline-JS syntaktisch gueltig
    try:
        i = s.rindex('<script>'); j = s.index('</script>', i)
        tmp = '/tmp/_pruefe_seite_inline.js'
        io.open(tmp, 'w', encoding='utf-8').write(s[i + 8:j])
        r = subprocess.run(['node', '--check', tmp], capture_output=True, text=True)
        if r.returncode:
            fehler.append('Inline-JS ungueltig:\n' + r.stderr.strip()[:600])
    except ValueError:
        hinweise.append('kein Inline-<script> gefunden, Syntaxpruefung uebersprungen')

    woerter = {l: woerterbuch(s, l) for l in SPRACHEN}
    if not all(woerter.values()):
        fehler.append('Woerterbuch nicht gefunden: '
                      + ' '.join('%s=%d' % (l, len(woerter[l])) for l in SPRACHEN))
        return fehler, hinweise

    dom = dom_schluessel(s)

    # 2 · Richtung eins: steht im DOM, fehlt im Woerterbuch
    for k in sorted(dom):
        fehlt = [l.upper() for l in SPRACHEN if k not in woerter[l]]
        if fehlt:
            fehler.append('Schluessel %s fehlt in %s' % (k, '/'.join(fehlt)))

    # 3 · keine deutschen Reste in IT und EN
    for k in sorted(dom):
        if k in GLEICH_OK or k not in woerter['de']:
            continue
        for l in ('it', 'en'):
            if woerter[l].get(k) == woerter['de'][k]:
                hinweise.append('%s: %s gleicht der DE-Fassung' % (l.upper(), k))

    if alt:
        # 4 · kein Copy-Verlust: jeder Wert von damals steht noch irgendwo,
        #     sei es live oder als auskommentierte Vorfassung
        for lang in SPRACHEN:
            for k, v in woerterbuch(alt, lang).items():
                if v not in s:
                    fehler.append('COPY-VERLUST %s.%s: %s' % (lang, k, v[:70]))

        # 5 · Richtung zwei: stand im DOM, ist verschwunden.
        #     Siehe Kopfkommentar — das ist die Richtung, die gefehlt hat.
        kommentare = ' '.join(re.findall(r'/\*.*?\*/', s, re.S))
        for k in sorted(dom_schluessel(alt) - dom):
            if k in kommentare:
                hinweise.append('%s ist ausgesetzt und nicht mehr im DOM' % k)
            else:
                fehler.append('ABSCHNITT WEG? %s stand im DOM und fehlt jetzt, '
                              'ohne Vermerk im Woerterbuch' % k)

    # 8 · kein Schluessel doppelt in einem Woerterbuch (WEB3): im Browser gilt
    #     sonst still der letzte, und die Seite zeigt nicht, was man liest
    live = {l: live_schluessel(woerterbuch_roh(s, l)) for l in SPRACHEN}
    for l in SPRACHEN:
        doppelt = sorted({k for k in live[l] if live[l].count(k) > 1})
        for k in doppelt:
            fehler.append('DOPPELT %s.%s steht %dx im Woerterbuch' % (l, k, live[l].count(k)))

    # 9 · alle drei Woerterbuecher mit denselben Schluesseln (WEB3)
    for l in ('it', 'en'):
        for k in sorted(set(live['de']) - set(live[l])):
            fehler.append('Schluessel %s fehlt in %s (steht in DE)' % (k, l.upper()))
        for k in sorted(set(live[l]) - set(live['de'])):
            fehler.append('Schluessel %s steht nur in %s, nicht in DE' % (k, l.upper()))

    # 10 · Markup = DE-Woerterbuch, wortgleich (WEB3; Alt-Texte siehe R2-WEB2-2)
    ohne_kommentar = re.sub(r'<!--.*?-->', ' ', s, flags=re.S)
    for m in re.finditer(r'<([a-z0-9]+)\b[^>]*\bdata-i18n="([a-z_0-9]+)"[^>]*>(.*?)</\1>',
                         ohne_kommentar, re.S):
        k, innen = m.group(2), m.group(3)
        if k not in woerter['de']:
            continue
        soll = json.loads(woerter['de'][k])
        if innen != soll:
            text = 'MARKUP %s ungleich DE: %r statt %r' % (k, innen[:60], soll[:60])
            (hinweise if (datei_name, k) in MARKUP_ALTBESTAND else fehler).append(
                text + (' (Altbestand, gemeldet in WEB3)' if (datei_name, k) in MARKUP_ALTBESTAND else ''))

    # 6 · keine neuen externen Verweise
    for u in sorted(set(re.findall(r'https?://[^"\'\\ )<]+', s))):
        if u not in BEKANNT:
            fehler.append('neuer externer Verweis: ' + u)

    # 7 · Bilder lokal, lazy unterhalb der Falz, unter der Groessengrenze
    if mit_bildern:
        falz = s.index('<!-- 2 · PROBLEM') if '<!-- 2 · PROBLEM' in s else 0
        for m in re.finditer(r'<img\b[^>]*>', sichtbar):
            tag, pos = m.group(0), m.start()
            treffer = re.search(r'src="([^"]*)"', tag)
            if not treffer or not treffer.group(1):
                continue
            src = treffer.group(1)
            if src.startswith(('http', '//')):
                fehler.append('externes Bild: ' + src)
                continue
            if pos > falz and 'loading="lazy"' not in tag:
                (hinweise if src in VORBESTAND else fehler).append(
                    'kein loading="lazy" unterhalb der Falz: ' + src
                    + (' (Altbestand)' if src in VORBESTAND else ''))
            # app.html und partner.html schreiben Pfade ab der Wurzel
            # ("/assets/…"); bis 22.11.2026 galten sie deshalb als fehlend.
            datei = src.lstrip('/')
            if os.path.exists(datei):
                kb = os.path.getsize(datei) / 1000
                grenze = 200 if datei.startswith('assets/foto/') else 250
                if kb > grenze:
                    fehler.append('%s ist %.0f KB (Grenze %d KB)' % (src, kb, grenze))
            elif 'onerror=' not in tag:
                fehler.append('%s fehlt und hat keinen onerror-Rueckfall' % src)
            else:
                hinweise.append('PLATZHALTER, Datei fehlt: ' + src)

    return fehler, hinweise


def selftest():
    """Beweist, dass Richtung zwei wirklich anschlaegt.

    Ein Gate, das nichts findet, weil es nichts anschaut, ist von einem gruenen
    Gate nicht zu unterscheiden. Also: einen Abschnitt kuenstlich entfernen und
    verlangen, dass der Pruefer meckert.
    """
    datei = next((d for d in ('prototyp2.html', 'index.html') if os.path.exists(d)),
                 'index.html')
    s = io.open(datei, encoding='utf-8').read()

    m = re.search(r'\n<section\b.*?\n</section>\n', s, re.S)
    if not m:
        print('FEHLGESCHLAGEN — kein <section> in %s gefunden' % datei)
        return 1
    verstuemmelt = s[:m.start()] + '\n' + s[m.end():]
    weg = sorted(dom_schluessel(s) - dom_schluessel(verstuemmelt))
    if not weg:
        print('FEHLGESCHLAGEN — der entfernte Abschnitt trug keine Schluessel, '
              'der Test prueft nichts')
        return 1

    fehler, _ = pruefe(verstuemmelt, s, mit_bildern=False)
    treffer = [f for f in fehler if f.startswith('ABSCHNITT WEG?')]
    if not treffer:
        print('FEHLGESCHLAGEN — Abschnitt mit %d Schluesseln entfernt (%s …), '
              'Pruefer blieb still. Genau dieser Fall ist der Grund fuer die '
              'zweite Richtung.' % (len(weg), ', '.join(weg[:3])))
        return 1

    fehler_sauber, _ = pruefe(s, s, mit_bildern=False)
    falsch = [f for f in fehler_sauber if f.startswith('ABSCHNITT WEG?')]
    if falsch:
        print('FEHLGESCHLAGEN — unveraenderte Datei meldet ABSCHNITT WEG:\n  '
              + '\n  '.join(falsch[:3]))
        return 1

    # WEB3: die Punkte 8–10 schlagen an, und eine auskommentierte Vorfassung nicht
    de = woerterbuch(s, 'de')
    k = next(x for x in sorted(set(re.findall(r'data-i18n="([a-z_0-9]+)"', s))) if x in de and x not in GLEICH_OK)
    blob_de = woerterbuch_roh(s, 'de')
    if len(live_schluessel(blob_de)) != len(de):
        print('FEHLGESCHLAGEN — live_schluessel findet %d, woerterbuch %d Schluessel in DE'
              % (len(live_schluessel(blob_de)), len(de)))
        return 1
    faelle = [
        ('DOPPELT', blob_de + ',\n  %s:"doppelt"' % k, 'de', 'DOPPELT de.%s' % k),
        ('IT ohne Schluessel', re.sub(r'(?m)(^\s*|[,{]\s*)%s:"(?:[^"\\]|\\.)*",?' % k, r'\1',
                                      woerterbuch_roh(s, 'it'), count=1), 'it', 'Schluessel %s fehlt in IT' % k),
    ]
    for name, neu_blob, lang, erwartet in faelle:
        t = s.replace(woerterbuch_roh(s, lang), neu_blob, 1)
        fe, _ = pruefe(t, None, mit_bildern=False)
        if not any(f.startswith(erwartet) for f in fe):
            print('FEHLGESCHLAGEN — %s nicht gemeldet (erwartet: %s)' % (name, erwartet))
            return 1
    markup = re.sub(r'(data-i18n="%s"[^>]*>)' % k, r'\1VERAENDERT ', s, count=1)
    if not any(f.startswith('MARKUP %s' % k) for f in pruefe(markup, None, mit_bildern=False)[0]):
        print('FEHLGESCHLAGEN — Markup ungleich DE bei %s nicht gemeldet' % k)
        return 1
    alt_fassung = s.replace(blob_de, blob_de + '\n  /* Vorherige Fassung: */ // %s:"alt",' % k, 1)
    if any(f.startswith('DOPPELT') for f in pruefe(alt_fassung, None, mit_bildern=False)[0]):
        print('FEHLGESCHLAGEN — eine auskommentierte Vorfassung gilt als doppelter Schluessel')
        return 1

    print('OK — Abschnitt mit %d Schluesseln entfernt, %d davon gemeldet. '
          'Unveraenderte Datei bleibt still. Doppelt, fehlende Sprache und Markup '
          'ungleich DE werden gemeldet, eine auskommentierte Vorfassung nicht.' % (len(weg), len(treffer)))
    return 0


def main():
    args = [a for a in sys.argv[1:]]
    if '--help' in args or '-h' in args:
        usage()
    if '--selftest' in args:
        sys.exit(selftest())

    datei = args[0] if args else 'index.html'
    basis = args[1] if len(args) > 1 else 'HEAD'
    if not os.path.exists(datei):
        print('Datei nicht gefunden: ' + datei, file=sys.stderr)
        sys.exit(2)

    s = io.open(datei, encoding='utf-8').read()
    alt = subprocess.run(['git', 'show', '%s:%s' % (basis, datei)],
                         capture_output=True, text=True).stdout

    fehler, hinweise = pruefe(s, alt, datei_name=os.path.basename(datei))
    for h in hinweise:
        print('  hinweis  ' + h)
    for f in fehler:
        print('  FEHLER   ' + f)

    woerter = {l: woerterbuch(s, l) for l in SPRACHEN}
    if fehler:
        print('FEHLGESCHLAGEN — %d Fehler in %s' % (len(fehler), datei))
    else:
        print('OK — %s: %d Schluessel im DOM, %s im Woerterbuch'
              % (datei, len(dom_schluessel(s)),
                 '/'.join(str(len(woerter[l])) for l in SPRACHEN)))
    sys.exit(1 if fehler else 0)


if __name__ == '__main__':
    main()
