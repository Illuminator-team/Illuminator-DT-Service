FROM ait1/rdp-data-crawler@sha256:4f564e68c85937ef1513a15326ba02b5024b24e1cc734cf5ca7a4c21f037507c

# Update domain to fix SSL issues and 404s
RUN sed -i 's/dataset.api.hub.zamg.ac.at/dataset.api.hub.geosphere.at/g' /data_crawler/sources/zamg.py
