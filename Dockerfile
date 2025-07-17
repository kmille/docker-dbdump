FROM python:3.13-alpine3.22 AS builder
RUN pip install poetry
COPY . /app
WORKDIR /app
RUN poetry build --format=wheel


FROM python:3.13-alpine3.22
ENV PYTHONUNBUFFERED=TRUE
RUN apk add --no-cache bash docker gzip

COPY --from=builder /app/dist/docker_dbdump*.whl .
RUN pip install docker_dbdump*.whl && \
    rm docker_dbdump*.whl

CMD ["/usr/local/bin/docker-dbdump"]
