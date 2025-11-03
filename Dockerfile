# از ایمیج Playwright با پایتون
FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

# نصب tor
RUN apt-get update && apt-get install -y tor && apt-get clean

# مسیر کاری
WORKDIR /app

# کپی نیازمندی‌های پایتون
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# کپی سورس پروژه
COPY . /app

# ساخت فولدر برای tor instances
RUN mkdir -p /app/tor_instances/tor1 /app/tor_instances/tor2 /app/tor_instances/tor3 /app/tor_instances/tor4 \
    && mkdir -p /app/tor_logs

# اضافه کردن فایل‌های کانفیگ
COPY tor-configs /app/tor-configs

# پورت‌های مورد نیاز
EXPOSE 4200 9050-9057

# استارت اپ (اول tor ها، بعد uvicorn)
CMD bash -c "\
tor -f /app/tor-configs/tor1.conf & \
tor -f /app/tor-configs/tor2.conf & \
tor -f /app/tor-configs/tor3.conf & \
tor -f /app/tor-configs/tor4.conf & \
uvicorn api_server:app --host 0.0.0.0 --port 4200 --log-level info"
