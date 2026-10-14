# NeoMarket — GitHub Actions CI/CD + staging VPS

Дата: 14 октября 2026. Этот набор заменяет **GitLab CI/CD**, но не меняет исходники приложения.

> **Статус:** конфигурации проверены статически; GitHub-hosted workflow, Docker build и реальный VPS в этой среде не запускались. Это стартовый набор для настройки, не свидетельство успешно работающего staging.

## Что внутри

- `.github/workflows/neomarket-staging.yml`: проверки PR/push, PostgreSQL 16 и Redis 7, сборка B2B/B2C/Admin в GHCR; **deployment только при ручном запуске из ветки `staging`**.
- `ci/`: проверочные скрипты, миграции и интеграционные тесты. Для GitHub runner PostgreSQL доступен по `127.0.0.1`, не по имени сервиса `postgres`.
- `deploy/staging/`: автономный Docker Compose, PostgreSQL/Redis, три API, NGINX только на `127.0.0.1:8080`, переменные, миграции, проверка портов и smoke-test.

Размещать содержимое архива нужно **в корне репозитория** NeoMarket, рядом с `pyproject.toml` и папкой `services/`.

## 1. Что учесть на VPS

**Ваш VPS:** Ubuntu (проверьте версию), 1 vCore, **1 ГБ RAM**, 40 ГБ SSD. Выделенных ресурсов недостаточно для надёжного одновременного запуска полной системы (B2B+B2C+Admin+PostgreSQL+Redis+NGINX). Скрипт `deploy.sh` по умолчанию **не запускает** полный стек при RAM ниже ~4 ГБ или свободном месте ниже 8 ГБ. **Не отключайте защиту** `ALLOW_LOW_MEMORY=1`: это может привести к OOM или повреждениям при прерванной записи. CI и сборку образов настройте уже сейчас; перед полноценным staging увеличьте память минимум до **4 ГБ** (лучше 8), CPU минимум до 2 vCore.

Пароль root, ранее отправленный в чат, **считайте раскрытым**; смените через `passwd`. Для CI используйте **отдельного пользователя `deploy` и SSH-ключ**. Приватный ключ не публикуйте и не коммитьте. Никаких секретов БД и SSH в репозитории.

## 2. Создайте GitHub-репозиторий

1. Откройте GitHub → New repository → **Private**.
2. Загрузите проект NeoMarket из вашего локального git, не архивом с `.venv`, логами и `.env`.
3. Создайте ветку `staging`, защитите `main` и `staging` правилами branch protection/rulesets: PR перед merge, ограничение write-доступа.
4. Добавьте файлы из этого набора в корень репозитория. Существующие workflow в `.github/workflows/` останутся на месте и могут запускаться дополнительно. Чтобы избежать дублей, после проверки нового workflow можно отключить старые workflow.
5. Проверьте `Settings → Actions → General`: Actions разрешены; для `GITHUB_TOKEN` в workflow выделяется `packages: write` на job `build`.

### Как запустить первый CI

При push/PR в `main` или `staging` стартуют проверки. Сборка в GHCR производится **только на push/ручном запуске ветки `staging`** и только после проверок. Защищайте staging от непроверенных изменений.

### Как запустить деплой

`Actions → NeoMarket - verify, build, staging deploy → Run workflow → Branch: staging → Run workflow`. Файл workflow для кнопки `Run workflow` должен также присутствовать **в default branch** (как правило `main`). При ручном запуске снова выполняются тесты и сборка, затем происходит выкладка.

Важно: GitHub на некоторых бесплатных тарифах **не предоставляет required reviewers и environment secrets для приватных репозиториев**. Поэтому не считайте имя `environment: staging` заменой approval. В этом наборе безопасность обеспечивается запуском `workflow_dispatch`, контролем защищённой ветки и repository secrets. Для приватного репозитория используйте именно **Repository secrets** (`Settings → Secrets and variables → Actions`).

## 3. Подготовьте VPS (Ubuntu 24.04)

Сначала подключитесь как администратор, обновите пароль root и откройте вторую SSH-сессию для проверки доступа:

```bash
ssh root@YOUR_VPS_IP
passwd
apt update && apt upgrade -y
apt install -y ca-certificates curl gnupg openssl git ufw fail2ban python3 rsync
ufw allow OpenSSH
ufw enable
```

Установите Docker Engine и Compose plugin **из официального репозитория** (не через случайный curl|sh): https://docs.docker.com/engine/install/ubuntu/

```bash
docker version
docker compose version
adduser --disabled-password --gecos '' deploy
usermod -aG docker deploy
install -d -o deploy -g deploy -m 0750 /opt/neomarket-staging
install -d -o root -g deploy -m 0750 /etc/neomarket
install -d -o deploy -g deploy -m 0700 /home/deploy/.ssh
```

Группа Docker на хосте даёт root-подобные привилегии — доступ к деплою ограничьте проверенным владельцем репозитория. Публичный SSH root по паролю отключайте **только после** проверки доступа по ключу к отдельному пользователю.

### SSH-ключ для GitHub Actions

На локальном **Windows PowerShell**:

```powershell
ssh-keygen -t ed25519 -f "$HOME\.ssh\neomarket_staging_ci" -C "neomarket-staging-github"
Get-Content "$HOME\.ssh\neomarket_staging_ci.pub"
```

Установите выведенный публичный ключ в `/home/deploy/.ssh/authorized_keys` на VPS, выставьте права:

```bash
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

Проверьте из PowerShell:

```powershell
ssh -i "$HOME\.ssh\neomarket_staging_ci" deploy@YOUR_VPS_IP 'id && docker ps'
```

### Проверка SSH host key

На VPS в доверенной административной сессии:

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

На компьютере:

```powershell
ssh-keyscan -t ed25519 YOUR_VPS_IP > "$HOME\.ssh\neomarket_staging_known_hosts"
ssh-keygen -lf "$HOME\.ssh\neomarket_staging_known_hosts"
```

Сверьте fingerprint с командой на сервере. Не используйте `StrictHostKeyChecking=no`.

### GitHub Secrets

`Settings → Secrets and variables → Actions → New repository secret`:

| Name | Value |
|---|---|
| `STAGING_SSH_HOST` | IP VPS |
| `STAGING_SSH_PORT` | `22` или другой настроенный порт |
| `STAGING_SSH_USER` | `deploy` |
| `STAGING_SSH_PRIVATE_KEY` | Содержимое приватного ED25519-ключа из PowerShell `Get-Content ... -Raw` |
| `STAGING_SSH_KNOWN_HOSTS` | Содержимое проверенного файла `known_hosts` |

Не используйте root-пароль в GitHub secrets.

## 4. Инициализация конфигурации на VPS

До первого deploy скопируйте каталог `deploy/staging/` из репозитория в `/opt/neomarket-staging/`. Можно временно использовать `scp`/`rsync` с локального компьютера, либо выполнить `git clone` на сервере с read-only deploy key (но не копируйте .env из репозитория). Каталог должен принадлежать пользователю `deploy`.

```bash
sudo python3 /opt/neomarket-staging/bootstrap_secrets.py
sudo chown root:deploy /etc/neomarket/staging.env
sudo chmod 640 /etc/neomarket/staging.env
sudo -u deploy test -r /etc/neomarket/staging.env
```

Скрипт откажется перезаписывать существующие секреты и не выводит их в лог. Обязательно сохраните резервную копию секретов в безопасном внешнем хранилище.

## 5. Авторизуйте VPS в GHCR только для чтения

GitHub Actions публикует образы с автоматическим `GITHUB_TOKEN`, **создавать PAT для публикации в Actions не требуется**.

Для `docker pull` приватного GHCR с VPS создайте в GitHub `Personal access token (classic)` с **read:packages**, желательно на отдельной machine account с доступом только к необходимым образам. При необходимости настройте доступ package к репозиторию/аккаунту.

Войдите на VPS под `deploy` и выполните:

```bash
read -r -p 'GitHub username: ' GH_USER
read -rs -p 'GHCR read-only PAT: ' GH_PAT; echo
printf '%s' "$GH_PAT" | docker login ghcr.io -u "$GH_USER" --password-stdin
unset GH_USER GH_PAT
chmod 600 "$HOME/.docker/config.json"
```

Убедитесь, что команды выполняет пользователь `deploy` (проверьте `whoami` и `echo "$HOME"`). **Не выполняйте этот docker login через sudo**, если deploy использует rootful Docker Engine и доступ к daemon имеет через группу `docker`.

## 6. Первый прогон и проверка

1. Убедитесь, что workflow есть в `main` и `staging`.
2. Сделайте push в `staging`, откройте **Actions** и проверьте `verify`, `integration` и три сборки `build`.
3. Найдите в GitHub Packages образы `ghcr.io/<owner>/<repo>/b2b:<full-sha>` и аналоги B2C/Admin. Они должны успешно скачиваться пользователем `deploy` с VPS.
4. После обновления VPS до **минимум 4 ГБ RAM** запустите workflow вручную из ветки `staging` (п.2).
5. Проверьте вывод `deploy_staging` и на VPS:

```bash
cd /opt/neomarket-staging
docker compose --env-file /etc/neomarket/staging.env --env-file .release.env -f docker-compose.staging.yml ps
bash smoke.sh
```

6. Доступ к staging из Windows по SSH-туннелю:

```powershell
ssh -N -L 8080:127.0.0.1:8080 -i "$HOME\.ssh\neomarket_staging_ci" deploy@YOUR_VPS_IP
```

Во второй консоли:

```powershell
curl.exe -i -H "Host: b2c.internal" http://127.0.0.1:8080/health
curl.exe -i -H "Host: b2b.internal" http://127.0.0.1:8080/health
```

Не открывайте `5432`, `6379`, `8001`, `8002`, `8003`, `8080` в публичном firewall. Gateway настроен только на `127.0.0.1`.

## 7. Сохранность данных

Staging Compose хранит PostgreSQL и Redis в **именованных Docker volumes**. Не выполнять `docker compose down -v` и `docker volume prune`, если важно сохранить данные. Настройте шифрованный off-site backup и испытайте restore **до** тестирования с реальными данными. Команды деплоя не удаляют Docker volumes; откат приложения возможен только при обратной совместимости миграций — **не откатывайте схему БД автоматически**.

## 8. Оговорки

- Сборка будет происходить на GitHub Runner. VPS **не собирает образы**.
- Пайплайн ранее не исполнялся на GitHub; статические проверки не гарантируют зелёный CI.
- В проекте уже есть старые `.github/workflows/` — новый workflow добавляется рядом. Некоторые старые проверяют устаревшие canonical сценарии: после перехода необходимо решить, какие сохранять, чтобы они не блокировали релизы по неактуальным требованиям.
- `deploy.sh` проверяет конфигурацию портов, но **не является полноценным backup/rollback механизмом**.
- На GitHub Free private repo ограничения Environment approval могут не позволить required reviewers. Сохраняйте ручной запуск и защищённые ветки.
- Более строгий production-пайплайн требует pinning всех GitHub Actions к commit SHA, SBOM, image signing, vulnerability gates, cloud IAM/OIDC, PITR и отдельно проверенного восстановления после инцидента.

## Документация

- https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow
- https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
- https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
- https://docs.docker.com/engine/install/ubuntu/
