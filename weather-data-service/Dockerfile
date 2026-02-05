FROM ait1/rdp-data-crawler:latest-dev

# Update domain to fix SSL issues and 404s
RUN sed -i 's/dataset.api.hub.zamg.ac.at/dataset.api.hub.geosphere.at/g' /data_crawler/sources/zamg.py
