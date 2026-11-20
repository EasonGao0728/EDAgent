FROM iedaopensource/release@sha256:8f6c311485c77374ccea149b2cc54d02ed789b189161daa223b1996ceb38f8e2
ADD runtime.tar.gz /opt/
COPY iEDA /usr/local/bin/iEDA
RUN chmod 755 /usr/local/bin/iEDA /opt/runtime/iEDA /opt/runtime/ld-linux-x86-64.so.2
ENV TCL_LIBRARY=/opt/runtime/tcl8.6
ENV PATH=/usr/local/bin:/usr/bin:/bin
LABEL org.aieda.runtime.sha256="d9ae28962bf622f1139e2b438c6f69deb646d93a48ece783da80a082d607694a"
