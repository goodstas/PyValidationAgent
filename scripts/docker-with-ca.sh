#!/bin/sh
# Build-time helper: run a command trusting the optional `extra_ca` BuildKit secret (a TLS-intercepting proxy's CA).
# The bundle is only visible during that RUN step and is never stored in the image.
if [ -s /run/secrets/extra_ca ]; then
  export SSL_CERT_FILE=/run/secrets/extra_ca PIP_CERT=/run/secrets/extra_ca UV_NATIVE_TLS=1
fi
exec "$@"
