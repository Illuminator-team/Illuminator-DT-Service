# RedisInsight with the current Alpine security updates (openssl, ... in the base).
FROM redis/redisinsight@sha256:b5e19ee240abef6edb435871b90ff8a210995422e8e018ab61c0339d318a1f84
USER root
RUN apk upgrade --no-cache
USER node
