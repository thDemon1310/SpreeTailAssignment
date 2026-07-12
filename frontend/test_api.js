import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.response.use(
  (response) => {
    if (response.data && Array.isArray(response.data.results)) {
      response.data = response.data.results;
    }
    return response;
  }
);

async function test() {
  try {
    // Attempt to hit the real backend if running, or just mock the response
    const mockResponse = {
      data: {
        count: 1,
        next: null,
        previous: null,
        results: [{ id: 1, name: 'Test Group' }]
      }
    };
    
    // Simulate interceptor
    const norm = { ...mockResponse };
    if (norm.data && Array.isArray(norm.data.results)) {
      norm.data = norm.data.results;
    }
    
    console.log("Normalized data:", norm.data);
    console.log("Is array?", Array.isArray(norm.data));
  } catch (err) {
    console.error(err);
  }
}

test();
