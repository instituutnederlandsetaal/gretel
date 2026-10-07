#!/bin/sh
# Start a local Alpino parser in server mode.
set -eu

ALPINO_HOME=${ALPINO_HOME:-/opt/Alpino}
PORT=${PORT:-7001}
TIMEOUT=${TIMEOUT:-600000}
MEMLIMIT=${MEMLIMIT:-1500M}
export ALPINO_HOME
export TMPDIR=${TMPDIR:-/tmp}
export LD_LIBRARY_PATH=/usr/local/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export PROLOGMAXSIZE="$MEMLIMIT"

exec "$ALPINO_HOME/bin/Alpino" -notk -veryfast \
    "user_max=$TIMEOUT" server_kind=parse "server_port=$PORT" \
    assume_input_is_tokenized=on debug=0 end_hook=xml \
    -init_dict_p batch_command=alpino_server
