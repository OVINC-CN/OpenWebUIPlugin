## OpenWebUIPlugin

Plugin for Open WebUI

### Deploy

```yaml
services:
  oui_plugin:
    container_name: "oui_plugin"
    image: "ghcr.io/ovinc-cn/openwebuiplugin:0.1.0"
    platform: "linux/amd64"
    restart: "unless-stopped"
    command: 
      - "/bin/sh"
      - "-c"
      - "python manage.py migrate && gunicorn --bind \"[::]:8020\" -w 1 --threads 10 -k uvicorn_worker.UvicornWorker --proxy-protocol --proxy-allow-from \"*\" --forwarded-allow-ips \"*\" entry.asgi:application"
    networks:
      - "oui"
    ports:
      - "8020:8020"
    environment:
      # The following configurations do not need to be paid attention to for the time being
      - "ALLOWED_HOSTS=*"
      - "FRONTEND_URL=http://localhost"
      - "BACKEND_URL=http://localhost"
      - "CORS_ORIGIN_WHITELIST=http://localhost"
      - "OVINC_API_DOMAIN=http://localhost"
      - "OVINC_WEB_URL=http://localhost"
      - "LOCAL_MODE=True"
      # The following configurations need attention and modification
      # Application Configuration
      # (Optional) Secret Please find a UUID website to generate and replace it
      - "APP_CODE=oui_plugin"
      - "APP_SECRET=628aeb61-63c1-4cac-a978-acd38137f8cc"
      # MySQL
      - "DB_NAME=oui_plugin"
      - "DB_USER=root"
      - "DB_PASSWORD="
      - "DB_HOST=host.docker.internal"
      - "DB_PORT=3306"
      # Redis
      # If you use other Redis, you need to configure
      # If you use Redis in Compose, you can directly use the following configuration
      - "REDIS_HOST=redis"
      - "REDIS_PORT=6379"
      - "REDIS_PASSWORD="
      - "REDIS_DB=0"
      # OpenWebUI
      - "OPENWEBUI_URL=http://openwebui:8000"
      - "OPENWEBUI_KEY=sk-"
      # Admin Account
      - "ADMIN_USERNAME=admin"
      - "ADMIN_PASSWORD="
      # Default 1M Token Price
      - "DEFAULT_TOKEN_PRICE=60"
      # The prefix that needs to be removed from the model. Generally, no configuration is required
      # If your model is not consistent with the official website, for example, if your model is o-gpt-4o, fill in o-
      # Tokens will be calculated according to gpt-4o when billing
      - "MODEL_PREFIX_TO_REMOVE="
      # Whether to ignore the model name (only related to token calculation, not model price)
      # Suitable for scenarios with limited memory, because loading Encoder will take up more memory
      # If omitted, all models will use the default model's Encoder to calculate Tokens
      - "IGNORE_MODEL_ENCODING=False"
      # Default Model
      - "DEFAULT_MODEL_FOR_TOKEN=gpt-4o"
  redis:
    container_name: "redis"
    image: "redis:7.4.0"
    restart: "unless-stopped"
    networks:
      - "oui"
    volumes:
      - "./redis/data:/data"
networks:
  oui:
```
