import {
  compressData,
  decompressData,
} from "@excalidraw/excalidraw/data/encode";
import { generateEncryptionKey } from "@excalidraw/excalidraw/data/encryption";

export type Frame = {
  time: number;
  view: [number, number, number, number];
  point: [number, number] | null;
};

export type Snapshot = { image: string; width: number; height: number };
export type Clip = Snapshot & { version: 1; audio: string; frames: Frame[] };

export async function shareClip(clip: Clip, location: Location) {
  const key = await generateEncryptionKey("string");
  const payload = await compressData(
    new TextEncoder().encode(JSON.stringify(clip)),
    { encryptionKey: key },
  );
  const response = await fetch(import.meta.env.VITE_APP_BACKEND_V2_POST_URL, {
    method: "POST",
    body: payload.buffer,
  });
  if (!response.ok) {
    throw new Error("上传失败，请重试或缩短片段");
  }
  const { id } = await response.json();
  if (typeof id !== "string" || !/^[a-zA-Z0-9_-]+$/.test(id)) {
    throw new Error("服务未生成链接，请缩短片段后重试");
  }
  const url = new URL(location.href);
  url.hash = `replay=${id},${key}`;
  return url.href;
}

export async function loadClip(hash: string): Promise<Clip> {
  const match = /^#replay=([a-zA-Z0-9_-]+),([a-zA-Z0-9_-]+)$/.exec(hash);
  if (!match) {
    throw new Error("无效的讲解链接");
  }
  const response = await fetch(
    import.meta.env.VITE_APP_BACKEND_V2_GET_URL + match[1],
  );
  if (!response.ok) {
    throw new Error("无法读取讲解");
  }
  const { data } = await decompressData(
    new Uint8Array(await response.arrayBuffer()),
    { decryptionKey: match[2] },
  );
  const clip = JSON.parse(new TextDecoder().decode(data)) as Clip;
  if (
    clip.version !== 1 ||
    !clip.image?.startsWith("data:image/svg+xml;") ||
    !clip.audio?.startsWith("data:audio/") ||
    !(clip.width > 0 && clip.height > 0) ||
    !Array.isArray(clip.frames) ||
    !clip.frames.length ||
    !clip.frames.every(
      (f) =>
        Number.isFinite(f.time) &&
        f.view?.length === 4 &&
        f.view.every(Number.isFinite) &&
        f.view[2] > 0 &&
        f.view[3] > 0 &&
        (f.point === null ||
          (f.point?.length === 2 && f.point.every(Number.isFinite))),
    )
  ) {
    throw new Error("讲解内容无效");
  }
  return clip;
}

export function frameAt(frames: Frame[], time: number) {
  let low = 0;
  let high = frames.length;
  while (low + 1 < high) {
    const mid = (low + high) >>> 1;
    if (frames[mid].time <= time) {
      low = mid;
    } else {
      high = mid;
    }
  }
  return frames[low];
}

export function dataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}
