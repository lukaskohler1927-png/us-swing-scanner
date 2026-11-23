# US Swing Scanner

Trade

Tägliche Long- und Short-Setups für die manuelle Chartprüfung in IBKR. Der Scanner läuft in einem öffentlichen GitHub-Repository auf einem Standard-Linux-Runner. Er hat weder eine Orderfunktion noch eine Verbindung zum IBKR-Konto. Die Nachrichtenanalyse arbeitet regelbasiert. Das Smartphone wird nur für die Einrichtung und für Telegram gebraucht.

## Was schon getestet wurde

Am 23. November 2026 lief der Abruf beider Nasdaq-Trader-Dateien durch. Nach dem Wertpapierfilter blieben 2’895 Nasdaq-, 1’986 NYSE- und 257 NYSE-American-Aktien übrig. Die 5’138 Werte sind die Ausgangsliste. Der Kurs-, Historien-, Liquiditäts- und Spreadfilter folgt bei jedem Scandurchlauf. Auf Wunsch kommt ein separates ETF-Segment einschließlich NYSE Arca dazu. Ein unabhängiger Datenquellentest verarbeitete 100 echte IBM-Tageskerzen bis zum 20. November sowie eine echte Apple-Ergebnismeldung aus EDGAR.

Der historische Lauf auf 505 Aktien ist in `research/historical.json` dokumentiert. Der getrennte Test erzielte nach Modellkosten einen Profit Factor von 0,60. Echtgeldmeldungen sind standardmässig gesperrt. Der persönliche Alpaca-SIP-Abruf, der erste GitHub-Lauf und der echte Telegram-Empfang müssen unter deinem Konto bestätigt werden. Die automatisierten Zustellungstests verwenden einen simulierten Telegram-Endpunkt.

## Einrichtung am Android-Handy

1. Lege auf GitHub ein **öffentliches** Repository `us-swing-scanner` mit aktiviertem **Add README** an. Gib dieses Repository in der ChatGPT-GitHub-Verbindung frei. ChatGPT kann den Quellstand danach einspielen, sofern die Verbindung Schreibrechte für Inhalte und Workflows besitzt. Falls die Verbindung keine Workflow-Dateien schreiben darf, beschreibt `ANDROID.md` den Import im Handy-Browser.
2. Öffne Alpaca und erstelle ein kostenloses **Paper Only**-Konto im Basic-Tarif. Öffne im Paper-Dashboard die API Keys und generiere den Key und das Secret. Ein Live-Konto, Einzahlung und Marktdaten-Upgrade sind für den Scanner überflüssig. Bei einem verweigerten SIP-Abruf beendet die Software den Lauf. [Alpaca Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading) · [Free Basic](https://docs.alpaca.markets/us/docs/about-market-data-api) · [verzögerte SIP-Daten](https://docs.alpaca.markets/us/docs/market-data-faq)
3. Öffne in Telegram den verifizierten **@BotFather**, sende `/newbot`, vergib Name und Benutzername. Öffne danach **deinen eigenen neuen Bot**. [BotFather](https://t.me/BotFather) · [Telegram-Anleitung](https://core.telegram.org/bots/tutorial)
4. Öffne im GitHub-Handybrowser **Repository → Settings → Secrets and variables → Actions → New repository secret**. Falls das Menü fehlt, aktiviere im Browser die Desktopansicht. Speichere die vier folgenden Werte ausschliesslich als Secrets. [GitHub-Anleitung](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)

| Secret | Wert |
|---|---|
| `ALPACA_KEY_ID` | Key ID aus dem Alpaca-Paper-Dashboard |
| `ALPACA_SECRET_KEY` | Zugehöriger geheimer Schlüssel |
| `TELEGRAM_BOT_TOKEN` | Token von BotFather |
| `TELEGRAM_PAIR_CODE` | Ein selbst gewählter, zufälliger Einmalcode von mindestens 16 Zeichen, ohne Leerzeichen. Ein Passwortgenerator eignet sich dafür. |

5. Sende **im privaten Chat mit deinem eigenen Bot** `/start DEIN_EINMALCODE`. Öffne innerhalb von 15 Minuten auf GitHub **Actions → US Swing Scanner → Run workflow → pair-test → Run workflow**. Der Workflow erwartet die korrekte Phrase aus genau einem privaten Chat. Der Bot bestätigt dort den technischen Test. Dadurch entfällt eine Suche nach deiner Chat-ID. Der Test lässt sich nach erfolgreicher Zustellung pro UTC-Tag einmal versenden. Nach der Kopplung kannst du das Kopplungs-Secret löschen. Bot-Token und Alpaca-Schlüssel bleiben in GitHub Secrets.
6. Starte im gleichen Menü **backtest**. Die jüngsten vier Jahre werden auf einem festen US-Aktienpanel geprüft. Die letzten zwölf Monate bilden den getrennten Test. Die Zusammenfassung erscheint auf der Seite des Workflow-Laufs. Fehlt dieser Schritt, versucht der erste Abendscan ihn automatisch. Der Scanner beginnt danach im Paper-Modus.
7. Möchtest du die berechneten Paper-Setups direkt erhalten, setze unter **Secrets and variables → Actions → Variables** die Repository-Variable `PAPER_TELEGRAM` auf `true`. Jede solche Nachricht trägt **PAPER**. Ohne die Variable werden die Ideen nur protokolliert. Betriebsberichte stehen auf GitHub. Für einen Tag ohne qualifiziertes Setup gibt es keine neue Signalnachricht.

Die vier Secrets niemals als Workflow-Eingaben, normale Variablen, Dateien oder Chatnachricht eintragen. Keine Fremdbots zur Ermittlung der Chat-ID nötig. Optional kannst du vor der ersten Kopplung ein separates Secret `STATE_KEY` aus mindestens 32 zufälligen Zeichen setzen. Ohne dieses Secret verschlüsselt der Scanner das Journal mit einem vom Alpaca-Secret abgeleiteten Schlüssel. Sichere den verwendeten Schlüssel in deinem Passwortmanager. Bei Rotation des Alpaca-Secrets kannst du den **alten** Wert als `STATE_KEY` hinterlegen, bevor du das neue Alpaca-Secret setzt. Ein nicht lesbares Journal stoppt den Lauf.

## Zeiten und Betrieb

| Aufgabe | Termin / Funktion |
|---|---|
| Vollscan | Montag bis Freitag 20:47 Uhr New Yorker Zeit. In Manila normalerweise 08:47 oder 09:47 Uhr am Folgetag. In der Schweiz normalerweise 02:47 Uhr am Folgetag, während der versetzten Zeitumstellungen 01:47 Uhr. |
| Eröffnungsprüfung | 11:17 Uhr New Yorker Zeit, nur für bereits vorgemerkte Ideen. Prüft die erste reguläre Minutenkerze. Das endgültige Paper-Ergebnis verwendet den Tagesbalken. Der Prüflauf eröffnet keine weiteren Ideen. |
| Sitzungskalender | XNYS, mit Feiertagen, Sommerzeit und verkürzten Sitzungen. Ein manueller Scan vor Handelsschluss plus 45 Minuten oder an einem Feiertag überspringt den Tag. |
| Internetstörung | Lesende Abfragen verwenden Zeitlimit, begrenzte Wiederholungen, Backoff und lokale, komprimierte Antwort-Caches. Bei einer HTTP-429-Antwort berücksichtigt der Reader numerische Retry-After-Werte. Keine IP-Wechsel. |
| Datendeckung | Jede Directory-Datei braucht einen plausiblen Zeitstempel und mindestens 1’000 Zeilen. Unter 70 % frischen Tageskursen für das gesamte Universum oder unter 95 % Antworten mit aktuellem Schlusskurs im zweiten Filterlauf wird kein neues Ergebnis publiziert. Der Bericht weist Teilabdeckung explizit aus. |
| Status | Erfolgreiche Abendläufe veröffentlichen nur aggregierte Zähler und Paper-Kennzahlen in `runtime/status.json`. Fehler und ausgelassene Termine stehen in der GitHub-Jobzusammenfassung. Das persönliche Journal liegt als `runtime/ledger.enc` verschlüsselt auf demselben Branch. |
| Wiederanlauf | Derselbe Session-Tag erzeugt höchstens einen Satz Ideen. Ein erfolgreicher Commit und Push reserviert jede Telegram-Sendung vor dem Versand. Eine unklare Telegram-Antwort wird als unbestätigt gezählt. Der Scanner verzichtet in diesem Fall auf eine automatische Wiederholung, damit keine doppelten Nachrichten entstehen. Ein verpasster Versand ist bei einem Abbruch in diesem Zeitfenster möglich. |
| Verpasste Tage | Bei der nächsten erfolgreichen Sitzung werden offene Paper-Positionen mit den verfügbaren Zwischentagen fortgeschrieben. Nach langer Lücke, fehlenden Kursen oder einer relevanten nachträglichen Kursanpassung lautet das Ergebnis „unbekannt“. Der Scanner schickt keine rückdatierten Einstiegsideen. |
| Grenzen | GitHub kann geplante Runs verzögern oder verwerfen. Bei 60 Tagen Repository-Inaktivität kann GitHub öffentliche Zeitpläne deaktivieren. In diesem Fall im Actions-Tab den Workflow wieder aktivieren. Der Abendjob publiziert bei erfolgreichem Lauf einen echten Projektbericht. [GitHub-Zeitplanung](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) |

## Was der Scanner prüft

- **Universum.** Nasdaq Trader liefert die Dateien `nasdaqlisted.txt` und `otherlisted.txt`. Der Code entfernt Testpapiere, auffälligen Nasdaq-Finanzstatus, unpassende Börsen und Instrumententypen, darunter viele Vorzugspapiere, Warrants, Units und SPACs. Es ist ein konservativer Namensfilter. Ungewöhnlich benannte Aktien können fehlen. US-Listing schliesst auch ausländische Stammaktien und manche ADRs ein. Bei `INCLUDE_ETFS=true` werden ETF-markierte Produkte getrennt geführt. Namensfilter entfernen erkennbare gehebelte und inverse Produkte. Höchstens ein ETF belegt einen der drei Plätze. [Nasdaq-Definitionen](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs)
- **Daten.** Alpaca liefert historische, splitbereinigte SIP-Tagesdaten in symbolübergreifenden Batches. Die Endzeit liegt mindestens 20 Minuten zurück. Der Schnellfilter läuft über die gesamte Ausgangsliste. Für liquide Werte folgt eine längere Historie. Pro Lauf werden identische Abrufe lokal wiederverwendet. Rohdaten bleiben auf dem temporären Runner. Yahoo/yfinance ist für diesen automatisierten Vollscan nicht eingebaut. Die öffentliche Chartansicht und die Datenlizenz sind verschiedene Dinge. TradingView wird nicht ausgelesen. [Alpaca-FAQ](https://docs.alpaca.markets/us/docs/market-data-faq) · [yfinance-Hinweise](https://github.com/ranaroussi/yfinance)
- **Handelbarkeit.** Letzter Schlusskurs mindestens 5 USD, 200 vollständige Sitzungen, plausibles OHLCV, Median des täglichen Dollarvolumens über 20 Vortage mindestens 5 Mio. USD, für Shorts 15 Mio. USD. ATR und Kurslücken begrenzen die zugelassene Volatilität. Relevanter Volumenausreisser, Gaps oder hohe Volatilität können Shorts ausschliessen. Auf den besten Kandidaten wird eine echte historische Geld-Brief-Stichprobe geprüft. Bis zu 30 verwertbare Quotes im Schlussfenster, mindestens drei verschiedene Zeitpunkte, 90. Perzentil höchstens 0,20 % für Long bzw. 0,15 % für Short. Der Quellenaufruf erfolgt für maximal 40 verschiedene Shortlist-Titel. Die Eröffnung am Folgetag kann einen anderen Spread haben.
- **Nachrichten.** Richtungsbezogene Earnings- und Guidance-Begriffe aus zeitgestempelten Einzelaktien-Schlagzeilen werden mit Gap, Volumen und Folgebestätigung durch den Kurs kombiniert. Mehrdeutige, hypothetische, gemischte oder nachträglich aktualisierte Nachrichten fallen aus der Prüfung. Optional aktiviert das Repository-Secret `SEC_USER_AGENT` mit eigener Kennung und echter Kontakt-E-Mail EDGAR. Bei höchstens 50 technisch vorgefilterten Kandidaten findet der Scanner bestätigte Form-8-K-Meldungen mit Item 2.02. Aus der Veröffentlichung allein wird kein positives oder negatives Ergebnis abgeleitet. Bei einem Ausfall läuft die technische Analyse weiter. Ein verlässlicher Kalender zukünftiger Earnings ist nicht enthalten. [Alpaca News](https://docs.alpaca.markets/us/docs/historical-news-data) · [SEC-Zugriff](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- **Modelle.** Momentum Breakout überschreitet das Hoch bzw. unterschreitet das Tief der vorherigen 20 Tage und verlangt zusätzlich Trend und Volumen. Trend Following prüft einen neuen MACD-Histogramm-Wechsel bei geordneten EMA 20/50/200 und passender EMA-50-Steigung. EMA Pullback verlangt einen Rücklauf zum EMA 20 und eine Schlusskerze in Trendrichtung. RSI Reversal prüft die Rückkehr über 32 bzw. unter 68 mit Preis- und Volumenbestätigung. News/Earnings kombiniert die genannten Ereignisse mit mindestens 1,8 % gerichteter Kurslücke und relativem Volumen von mindestens 1,6. Es gibt kein aus Tageskerzen geschätztes Intraday-VWAP.
- **Risiko.** Die Einstiegszone liegt bei Schlusskurs ±0,12 ATR. Der Stop folgt dem vorherigen Dreitagesextrem plus Puffer und hat einen Mindestabstand anhand des ATR. Das Ziel nutzt 85 % der vorherigen 20-Tage-Spanne, begrenzt auf 4,8 ATR und einen gegebenenfalls näheren 60-Tage-Widerstand bzw. eine Unterstützung. Nur bei netto mindestens 2:1 **vom ungünstigsten Rand der Zone** wird die Idee berücksichtigt. Prozentwerte in der Nachricht beziehen sich auf die Referenz in der Mitte und zeigen die Richtung der Positionsrendite. Stops können bei Kurslücken deutlich schlechter ausgeführt werden.
- **Score.** Ein erfülltes Setup gibt 50 Punkte. Relatives Volumen ergänzt 0–15 Punkte, Median-Dollarvolumen logarithmisch 0–10, Netto-CRV 0–15 und bestätigender Trend bzw. RSI-Umkehr 0 oder 10. Die genauen Formeln stehen in `swing/strategy.py`. Mindestscore 75. Die Rangfolge entscheidet erst nach Score, dann nach CRV, Symbol und Strategie. Der Score ist eine Kriterienwertung. Eine statistische Gewinnwahrscheinlichkeit wird nicht geschätzt.
- **Lebenszyklus.** Pro Sitzung höchstens drei neue Ideen, insgesamt höchstens neun offene bzw. vorgemerkte. Ein Symbol kann innerhalb von fünf Sitzungen nicht erneut vorgeschlagen werden. Modellierter Einstieg ausschliesslich zur folgenden regulären Eröffnung innerhalb der Zone. Eine verpasste Eröffnung lässt die Idee verfallen. Nachträglich ungültige, ursprünglich zugestellte Ideen erhalten eine eigene Meldung. Das Paper-Modell beendet eine offene Idee bei Stop, Ziel oder spätestens zum fünften Sitzungsschluss. Bei gleichem Tagesbalken für Stop und Ziel gilt der Stop zuerst. Bei Short immer die Leihbarkeit, den Leihsatz und das Gap-Risiko in IBKR prüfen.

## Backtest und Freigabe

| Kennzahl | Entwicklungszeitraum bis 30.06.2016 | Getrennter Test 01.07.2016–07.02.2018 |
|---|---:|---:|
| Ausgeführte Simulationen | 642 | 446 |
| Trefferquote nach Kosten | 40,3 % | 38,6 % |
| Profit Factor | 0,74 | 0,60 |
| Maximaler Drawdown zum Tagesschluss | 23,0 % | 23,6 % |
| Durchschnittliches geplantes Netto-CRV | 2,76 | 2,76 |
| Durchschnittliches realisiertes Ergebnis in R | −0,11 | −0,21 |
| Mangels Einstieg verfallene Ideen | 1’075 | 625 |

Die Quelldaten umfassen 619’017 verwendbare Tageskerzen von 505 damaligen S&P-500-Titeln ab Februar 2013. Die ersten 200 Sitzungen dienen als Indikatorhistorie. Der Backtest verwendet nur zu diesem Zeitpunkt bekannte Kursbalken für Entscheidungen und beginnt die simulierte Ausführung am nächsten Handelstag. Er erzwingt Flachstellung an der Zeitgrenze durch Weglassen neuer Ideen in den letzten fünf Sitzungen jeder Partition. Ein Test verändert künftige Kurse und prüft, ob frühere Indikatoren identisch bleiben. Positionsgrösse ist auf 10 % des aktuellen Modellkapitals oder 0,5 % Stoprisiko beschränkt. Drawdown wird auf aggregiertem, täglich bewertetem Kapital berechnet. Ein unbekannter Ausgang im Entwicklungszeitraum ist gesondert ausgewiesen. Für eine bereits eröffnete Position mit fehlendem Folgekurs wird das Portfolio mit einem Stoprisiko belastet.

Das Modell veranschlagt je Transaktionsseite 10 Basispunkte für Spread/Slippage und 5 Basispunkte für Gebühren, als Modell für etwa 1 USD je 2’000 USD Transaktionswert. Für Shorts sind zusätzlich 10 % jährliche Leihkosten angesetzt. In der CRV-Prüfung werden acht Kalendertage Leihe reserviert. Im Replay zählen die tatsächlich modellierten Kalendertage. Der persönliche IBKR-Tarif, Dividenden inklusive Short-Ersatzleistungen, individuelle Leihsätze und Steuern sind nicht rekonstruiert. Der echte Eröffnungsfill, ein handelbarer Spread und die Verfügbarkeit der Leihe sind nicht garantiert.

Die historische Liste ist eine spätere Auswahl von Indexmitgliedern. Es gibt **Survivorship Bias**, keine vollständige Historie delisteter Titel, keine historischen Quotes und keine vollständige Ereignischronik im Archiv. Der Ausführbarkeitstest mit echten Quote-Stichproben findet im Forward-Scan statt. Die archivierte Auswertung deckt die vier technischen Strategien ab. Die JSON-Datei schlüsselt die Ergebnisse nach Strategie und Richtung auf, auch kleine oder leere Gruppen. Ereignis- und ETF-Setups haben keine historische Freigabe. [Historisches Archiv](https://www.kaggle.com/datasets/camnugent/sandp500)

Der erneute Alpaca-Lauf benutzt ein vorgegebenes Panel liquider Aktien über vier Jahre. Ein Jahr bleibt als Out-of-Sample-Zeitraum zurück. Er ersetzt keinen marktweiten, historisch zeitpunktgetreuen Test. Die Auswertung wird spätestens nach rund 30 Tagen erneuert. Für eine spätere ausdrücklich aktivierte Variable `LIVE_ALERTS=true` müssen aktuelle Engine-Prüfsumme, Prüfung über dasselbe Datenfeed, positive OOS-Gesamtauswertung und positive OOS-Auswertung derselben Strategie/Richtung vorliegen. Jeweils mindestens 30 geschlossene Fälle, Profit Factor ≥1,10 und positives mittleres R. Weiter gelten mindestens 20 vollständige Forward-Scans und 20 abgeschlossene Paper-Fälle desselben Segments mit Profit Factor in R ≥1,10 und positivem mittlerem R. Die strikten Kriterien können auf unbestimmte Zeit zu null Handlungssignalen führen. Die Grundeinstellung bleibt Paper. Der alte Archivtest kann allein keine Telegram-Handlungssignale freischalten.

## Kosten und Betriebsgrenzen

Die bereitgestellten Workflows starten ausschliesslich in öffentlichen Repositories auf dem Standardrunner `ubuntu-24.04`. Sie verwenden keine kostenpflichtige API, keine Kreditkarte, keine automatisch verlängernde Testversion, keine grossen Runner und keine extern gespeicherten Actions-Artefakte oder Actions-Caches. Der Tagesjob erstellt und publiziert den Forschungsbericht dieses Projekts. Die persönliche Zustellung ist optional. Ein Lauf ist auf 55 Minuten begrenzt. Die Verfügbarkeit und zukünftige Tarifpolitik der Anbieter liegen ausserhalb des Projekts. Die Börse liefert dem Scanner keinen Realtime-Service oder zugesicherten Ausführungstermin. [GitHub-Preise](https://docs.github.com/en/billing/concepts/product-billing/github-actions) · [GitHub-Bedingungen für Actions](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features)

## Reproduktion für Entwickler

Python 3.12 und die fixierten Pakete aus `requirements.txt`. Das Handy braucht diese Entwicklungswerkzeuge nicht.

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m swing.cli health
python -m swing.backtest --archive sandp500.zip --output historical.json
```

Das Archiv lässt sich über die [öffentliche Kaggle-Download-API](https://www.kaggle.com/api/v1/datasets/download/camnugent/sandp500) beziehen. Die Prüfsumme der getesteten Datei steht in `research/historical.json`. Authentifizierte Datenendpunkte, Bot-Zustellung und Journal-Commits werden nur von expliziten CLI-Aufrufen bzw. dem Workflow verwendet. Das Repo enthält keine Zugangsdaten und keine Kurs-Rohdaten.
