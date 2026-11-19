/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    unoptimized: true,
  },
  experimental: {
    // Keep proxied multipart uploads intact; the backend accepts videos up to 250 MiB.
    proxyClientMaxBodySize: '260mb',
    // FFmpeg processing can outlast Next's 30-second proxy default.
    proxyTimeout: 10 * 60 * 1000,
  },
  async rewrites() {
    const configuredBackend = process.env.SPEECH2POST_BACKEND_URL || 'http://127.0.0.1:8000'
    const backendUrl = /^https?:\/\//.test(configuredBackend)
      ? configuredBackend
      : `http://${configuredBackend}`

    return [
      {
        source: '/backend/:path*',
        destination: `${backendUrl}/:path*`,
      },
    ]
  },
}

export default nextConfig
