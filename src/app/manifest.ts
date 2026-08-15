import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "AI Stock Signal",
    short_name: "AI Stock Signal",
    description: "本日のおすすめ株と保有株の売り時をAIでチェック",
    start_url: "/",
    display: "standalone",
    background_color: "#0a0a0a",
    theme_color: "#0a0a0a",
    icons: [
      {
        src: "/manifest-icon-192",
        sizes: "192x192",
        type: "image/png",
      },
      {
        src: "/manifest-icon-512",
        sizes: "512x512",
        type: "image/png",
      },
    ],
  };
}
