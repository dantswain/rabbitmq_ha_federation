#!/bin/bash

nodes=(rabbit1 rabbit2 rabbit3 rabbit4)
for node in "${nodes[@]}"
do
    url=http://$(docker-compose port ${node} 15672)
    echo "${node}: ${url}"
    open $url
done
