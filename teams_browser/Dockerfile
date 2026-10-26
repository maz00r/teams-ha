ARG BUILD_FROM=alpine:3.20
FROM ${BUILD_FROM}

# Chromium + wirtualny ekran (Xvfb) + VNC + noVNC (panel w przeglądarce przez Ingress).
# websocket-client: stdlib nie ma klienta ws, a CDP to websocket.
# Fonty noto: polskie znaki i emoji w czatach Teams.
RUN apk add --no-cache \
      chromium \
      xvfb \
      x11vnc \
      novnc \
      websockify \
      python3 \
      py3-pip \
      tzdata \
      font-noto \
      font-noto-emoji \
    && pip3 install --no-cache-dir --break-system-packages websocket-client

COPY cdp.py notifier.py panel.py panel.html /app/
COPY run.sh /run.sh
RUN chmod a+x /run.sh

ENV CHROME_PROFILE=/data/chrome-profile \
    DISPLAY=:1 \
    LANG=pl_PL.UTF-8 \
    PYTHONUNBUFFERED=1

CMD [ "/run.sh" ]
