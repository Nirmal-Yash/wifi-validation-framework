FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NETFORGE_PORT=5000
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 netforge
COPY . .
RUN mkdir -p db artifacts && chown -R netforge:netforge /app
USER netforge
EXPOSE 5000
CMD ["gunicorn","-w","2","--threads","4","--timeout","120","-b","0.0.0.0:5000","dashboard.enterprise_app:app"]
