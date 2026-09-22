"""Only read owned execution/graph snapshots. Never submit or retry model requests.
Install httpx in your own environment. Provide PX_API_TOKEN and optional PX_CA_CERT.
"""
import argparse
import os
import ssl
import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, help='HTTPS origin, without /api/console/v1')
    parser.add_argument('--session', required=True)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    token = os.environ.get('PX_API_TOKEN')
    if not token:
        parser.error('Set PX_API_TOKEN to your own revocable access token')
    if not args.base.startswith('https://'):
        parser.error('Use the configured HTTPS origin')
    for value in (args.session, args.run):
        if not value or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in value):
            parser.error('Use opaque session and run IDs, not paths')
    ca = os.environ.get('PX_CA_CERT')
    verify = ssl.create_default_context(cafile=ca) if ca else True
    with httpx.Client(base_url=args.base.rstrip('/') + '/api/console/v1/',
                      headers={'Authorization': 'Bearer ' + token}, verify=verify,
                      trust_env=False, timeout=20, follow_redirects=False) as client:
        root = f'sessions/{args.session}/runs/{args.run}'
        response = client.get(root + '/graphs')
        if response.status_code != 200:
            raise SystemExit(f'Graph directory returned HTTP {response.status_code}; no retry was sent')
        directory = response.json()
        print('Graph count:', directory['total'])
        for item in directory['items']:
            print('Status:', item['status'])
            if item['status'] not in ('ready', 'partial'):
                continue
            response = client.get(root + '/graphs/' + item['id'], params={'node_limit': 80, 'edge_limit': 160})
            if response.status_code != 200:
                raise SystemExit(f'Graph snapshot returned HTTP {response.status_code}; no retry was sent')
            graph = response.json()
            print('Nodes:', len(graph['nodes']), 'Edges:', len(graph['edges']), 'Truncated:', graph['meta']['truncated'])
            print('Data revision:', graph['meta']['data_revision'])


if __name__ == '__main__':
    main()
