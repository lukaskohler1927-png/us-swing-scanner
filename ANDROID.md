# Telegram am Android-Handy verbinden

Kurse und Börsenlisten funktionieren sofort ohne Registrierung. Der Zeitplan ist im öffentlichen Repository eingerichtet. Für Nachrichten auf deinem Handy sind zwei persönliche Werte nötig.

1. Öffne in Telegram den verifizierten [@BotFather](https://t.me/BotFather). Sende `/newbot` und folge den Fragen nach Name und Benutzername. Kopiere den Bot-Token. Wenn du bereits einen eigenen Bot hast, verwende dessen Token.
2. Öffne die [Actions-Secrets dieses Scanners](https://github.com/lukaskohler1927-png/us-swing-scanner/settings/secrets/actions). Tippe für jede Zeile auf **New repository secret**.

   | Name | Eintrag |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | Token von BotFather |
   | `TELEGRAM_PAIR_CODE` | Privater zufälliger Kopplungscode mit mindestens 16 Zeichen, ohne Leerzeichen |

3. Öffne den privaten Chat mit **deinem neuen Bot**. Sende `/start DEIN_CODE`, mit deinem tatsächlichen Kopplungscode nach dem Leerzeichen.
4. Öffne innerhalb von 15 Minuten den [Scanner-Workflow](https://github.com/lukaskohler1927-png/us-swing-scanner/actions/workflows/scanner.yml). Tippe **Run workflow**, wähle unter **Aufgabe** den Eintrag **pair-test**, dann nochmals **Run workflow**. Der Bot sendet eine Testnachricht. Jeder weitere manuelle Start von `pair-test` sendet erneut eine Bestätigung. Nach der Kopplung ist dafür keine neue Startnachricht an den Bot nötig. Den Kopplungscode kannst du danach aus den GitHub-Secrets löschen.

Speichere geheime Werte ausschliesslich in GitHub Secrets und verwende den Kopplungscode nur im privaten Bot-Chat. Der Token verschlüsselt standardmässig auch das Journal. Bei einer Tokenrotation setze **vorher** den alten Wert als Secret `STATE_KEY`, damit das Journal lesbar bleibt. Alternativ kannst du vor der ersten Kopplung einen stabilen, separaten Schlüssel mit mindestens 32 zufälligen Zeichen als `STATE_KEY` setzen. Ein bestehendes Journal benötigt seinen ursprünglich verwendeten Schlüssel.

Nach der Kopplung kommen qualifizierte Paper-Signale automatisch. Findet ein abgeschlossener Scan keine neuen gültigen Positionen, sendet der Bot einmal pro US-Handelstag eine kurze Bestätigung. Mit der Repository-Variable `PAPER_TELEGRAM=false` pausierst du die Paper-Signale und die Bestätigung bei null Treffern. Tagesberichte stehen im Actions-Tab. Zum Anhalten des Zeitplans verwende dort **US Swing Scanner → … → Disable workflow**.

Für einen manuellen Scan mit Versand tippe im [Scanner-Workflow](https://github.com/lukaskohler1927-png/us-swing-scanner/actions/workflows/scanner.yml) auf **Run workflow → jetzt-scannen → Run workflow**.
