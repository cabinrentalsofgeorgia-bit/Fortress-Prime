FROM paperclip-local:v2026.325.0

USER root

COPY patch-paperclip-image.js /tmp/patch-paperclip-image.js
RUN node /tmp/patch-paperclip-image.js && rm -f /tmp/patch-paperclip-image.js

USER node
