import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://10.5.0.71:5008';
const TIMEOUT = __ENV.HTTP_TIMEOUT || '30s';

const dashboardErrors = new Rate('dashboard_errors');
const dashboardLatency = new Trend('dashboard_latency', true);

export const options = {
  thresholds: {
    http_req_failed: ['rate<0.10'],
    http_req_duration: ['p(95)<4000', 'p(99)<8000'],
    dashboard_errors: ['rate<0.10'],
  },
  scenarios: {
    dashboard_payload: {
      executor: 'ramping-arrival-rate',
      exec: 'dashboardPayloadHotspot',
      startRate: 3,
      timeUnit: '1s',
      preAllocatedVUs: Number(__ENV.DASHBOARD_VUS || 20),
      maxVUs: Number(__ENV.DASHBOARD_MAX_VUS || 140),
      stages: [
        { duration: '30s', target: 8 },
        { duration: '45s', target: 15 },
        { duration: '45s', target: 25 },
        { duration: '45s', target: 35 },
        { duration: '15s', target: 0 },
      ],
      tags: { hotspot: 'dashboard_payload' },
    },
  },
};

export function dashboardPayloadHotspot() {
  const res = http.get(`${BASE_URL}/api/dashboard-data`, {
    timeout: TIMEOUT,
    tags: { app: 'malla', profile: 'dashboard-focus', endpoint: 'api_dashboard_data' },
  });

  dashboardLatency.add(res.timings.duration);
  dashboardErrors.add(res.status !== 200);

  check(res, {
    'status is 200': (response) => response.status === 200,
  });

  sleep(1);
}
