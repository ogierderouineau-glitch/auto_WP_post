/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    unoptimized: true,
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
