# Placeholder — not used until Phase 7 (deploy).
#
# Will need to handle device access (/dev/sr0) and access to
# /sys/bus/usb/drivers/usb/ for the unbind/rebind eject fallback, which
# means either --privileged or specific --device / cgroup rules. Worth
# deciding deliberately in Phase 7 rather than bolting on at the end.

FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

EXPOSE 5000
CMD ["python", "backend/app.py"]
