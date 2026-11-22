FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV container=docker

RUN sed -i 's|http://archive.ubuntu.com/ubuntu|http://mirrors.edge.kernel.org/ubuntu|g; s|http://security.ubuntu.com/ubuntu|http://mirrors.edge.kernel.org/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=10 -o Acquire::http::Timeout=30 update \
    && apt-get -o Acquire::Retries=10 -o Acquire::http::Timeout=30 install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    systemd systemd-sysv dbus sudo \
    ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg     && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc        | gpg --dearmor -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg     && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] https://apt.postgresql.org/pub/repos/apt noble-pgdg main"        > /etc/apt/sources.list.d/pgdg.list     && apt-get -o Acquire::Retries=10 -o Acquire::http::Timeout=30 update     && apt-get -o Acquire::Retries=10 -o Acquire::http::Timeout=30 install -y --no-install-recommends postgresql-client-17     && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /etc/systemd/system && \
    for unit in dev-hugepages.mount sys-fs-fuse-connections.mount \
        systemd-remount-fs.service getty.target \
        console-getty.service systemd-logind.service; do \
        ln -sf /dev/null "/etc/systemd/system/$unit"; \
    done

RUN useradd --create-home --shell /bin/bash restoretest \
    && echo 'restoretest ALL=(ALL) NOPASSWD: /usr/bin/systemctl' \
       > /etc/sudoers.d/restoretest \
    && chmod 0440 /etc/sudoers.d/restoretest

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

COPY entrypoint.py /usr/local/sbin/restore-test-entrypoint
COPY units/ /etc/systemd/system/

RUN chmod 0755 /usr/local/sbin/restore-test-entrypoint \
    && chmod 0644 /etc/systemd/system/restore-test-*.service \
    && mkdir -p /etc/systemd/system/multi-user.target.wants \
    && for unit in daphne celery celery-beat worker; do \
         ln -sf "/etc/systemd/system/restore-test-$unit.service" \
           "/etc/systemd/system/multi-user.target.wants/restore-test-$unit.service"; \
       done

STOPSIGNAL SIGRTMIN+3
ENTRYPOINT ["/usr/local/sbin/restore-test-entrypoint"]
