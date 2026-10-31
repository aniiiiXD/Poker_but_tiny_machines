FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /runtime
COPY supervisor.py /runtime/supervisor.py
RUN chmod 0555 /runtime /runtime/supervisor.py
ENTRYPOINT ["python", "-I", "-u", "/runtime/supervisor.py"]
