FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py publication_scope.py pc6.py pv.py grid.py grid_postgis.py wind.py wind_postgis.py heat.py heat_postgis.py ev.py ev_postgis.py consumption.py model_postgis.py postgis_sql.py layer-manifest.json ./

CMD ["python", "main.py"]
