docker compose on a swarm can't -- it just can't so here's teh fix:

docker stack deploy -c <(echo 'version: "3.9"' && docker compose --env-file ./cifs-secrets.env config | tail +2 -) servicename 
