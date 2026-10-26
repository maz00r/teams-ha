ARG BUILD_FROM=ubuntu:22.04
FROM ${BUILD_FROM}

ENV DEBIAN_FRONTEND=noninteractive

# Repozytoria Microsoftu: prod (microsoft-identity-broker) i edge (microsoft-edge-stable).
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg apt-transport-https \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/ubuntu/22.04/prod jammy main" > /etc/apt/sources.list.d/microsoft-prod.list \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/edge stable main" > /etc/apt/sources.list.d/microsoft-edge.list \
    && apt-get update && apt-get install -y --no-install-recommends \
      microsoft-edge-stable \
      microsoft-identity-broker \
      xvfb x11vnc novnc websockify \
      python3 python3-pip \
      dbus-x11 gnome-keyring libsecret-1-0 libsecret-tools \
      tzdata fonts-noto-core fonts-noto-color-emoji \
    && pip3 install --no-cache-dir websocket-client \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Gdzie usiadł broker i jak go odpala systemd — potrzebne, bo w kontenerze nie ma systemd.
RUN echo "=== pliki brokera ===" && dpkg -L microsoft-identity-broker | grep -E "bin|service|\.jar|exec" || true; \
    echo "=== service ExecStart ===" && grep -rhE "ExecStart" /usr/lib/systemd/*/microsoft-identity-broker* /lib/systemd/*/microsoft-identity-broker* 2>/dev/null || true; \
    echo "=== novnc ===" && ls /usr/share/novnc/core/rfb.js 2>/dev/null || true

# Polityka Edge: wymuś logowanie do przeglądarki (konto w profilu Edge) — to logowanie
# idzie przez brokera i rejestruje urządzenie w Entra ID (Workplace Join). Logowanie
# tylko w karcie Teams omija brokera i nie rejestruje. HideFirstRunExperience ucina
# ekran powitalny, żeby od razu było widać prośbę o konto.
RUN mkdir -p /etc/opt/edge/policies/managed \
    && printf '{\n  "BrowserSignin": 2,\n  "HideFirstRunExperience": true,\n  "SyncDisabled": true\n}\n' \
       > /etc/opt/edge/policies/managed/registration.json

COPY cdp.py notifier.py panel.py panel.html /app/
COPY run.sh /run.sh
RUN chmod a+x /run.sh

ENV EDGE_PROFILE=/data/edge-profile \
    DISPLAY=:1 \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1

CMD [ "/run.sh" ]
