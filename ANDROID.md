# Repository über das Smartphone einrichten

**Der kürzeste Weg mit ChatGPT.** Ein neues öffentliches Repository namens `us-swing-scanner` mit README anlegen. Öffne danach [Installierte GitHub-Apps](https://github.com/settings/installations), bei der ChatGPT-/Codex-App **Configure**, dann **Repository access → Only select repositories → us-swing-scanner → Save**. Alternativ in ChatGPT **Einstellungen → Plugins → GitHub → Repository-Zugriff verwalten** öffnen. Wenn die App dort erstmals installiert wird, **Install** wählen. Gib ChatGPT dann den Repository-Namen. [OpenAI-Anleitung](https://help.openai.com/en/articles/11145903-connecting-github-to-chatgpt)

**Handy-Import ohne verbundene Schreibrechte.** Das Downloadpaket enthält neben dem Quellordner die Datei `Android-Start.txt`. Sie ist ein einmalig zu kopierender GitHub-Workflow mit eingebettetem, komprimiertem Quellstand. Der folgende Weg funktioniert mit GitHub im Handy-Browser. Du benötigst keinen lokalen Python-Interpreter und keinen PC.

1. Entpacke das ZIP in der Samsung-App **Eigene Dateien**. Öffne `Android-Start.txt` mit einem Textbetrachter. Wähle **Alles auswählen → Kopieren**.
2. Öffne dein neues, leeres öffentliches Repository mit README im GitHub-Browser. Tippe auf **Add file → Create new file**. Falls nötig, beim Browser **Desktopwebsite** einschalten.
3. Gib als Dateinamen exakt `.github/workflows/scanner.yml` ein. Füge den kopierten Inhalt in den Editor ein. Tippe auf **Commit changes** und bestätige den Commit auf dem Standardbranch.
4. Öffne **Actions → US Swing Scanner → Run workflow** und wähle **health**. Beim ersten Lauf ergänzt der Workflow die Python-Dateien, Tests und Auswertung und veröffentlicht sie im Repository. Der Modus prüft die echten Symbolverzeichnisse. Die Scanner-Tests laufen auch in dieser Ein-Datei-Variante bei jedem Aufruf.
5. Folge im Repository der **README** ab dem Alpaca-Paper-Konto. Vor der Telegram-Kopplung ist keine Nachricht zu erwarten.

Falls GitHub das Schreiben mit „permission denied“ blockiert, prüfe im eigenen Repository **Settings → Actions → General** die Berechtigung für den Workflow zur Inhaltsaktualisierung und etwaige Branch-Regeln. Bei einem öffentlich gewordenen Token den Token bei BotFather widerrufen und den Ersatz direkt als GitHub Secret hinterlegen. Nutzer des optionalen separaten Journal-Schlüssels behalten diesen bei.

Zum Ausschalten genügt in GitHub **Actions → US Swing Scanner → … → Disable workflow**. Dies beendet die geplanten Läufe.
