import { useEffect, useRef, useState } from "react";
import { exportScene } from "@excalidraw/excalidraw";

import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";

import { dataUrl, frameAt, loadClip, shareClip } from "./storage";

import type { Clip, Frame, Snapshot } from "./storage";

import "./replay.css";

export function RecordEntry({ api }: { api: ExcalidrawImperativeAPI }) {
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const [error, setError] = useState("");
  async function open() {
    try {
      const state = api.getAppState();
      const elements = api
        .getSceneElements()
        .filter(
          (el) =>
            state.selectedElementIds[el.id] ||
            (el.type === "text" &&
              el.containerId &&
              state.selectedElementIds[el.containerId]),
        );
      if (!elements.length) {
        throw new Error("请先选中要分享的分支与上下文");
      }
      const svg = await exportScene({
        type: "svg",
        data: { elements, appState: state, files: api.getFiles() },
        config: {
          canvasBackgroundColor: state.viewBackgroundColor,
          embedScene: false,
        },
      });
      const image = await dataUrl(
        new Blob([svg.outerHTML], { type: "image/svg+xml" }),
      );
      setError("");
      setSnapshot({
        image,
        width: svg.viewBox.baseVal.width,
        height: svg.viewBox.baseVal.height,
      });
    } catch (e) {
      setError(String(e));
    }
  }
  return snapshot ? (
    <Studio snapshot={snapshot} close={() => setSnapshot(undefined)} />
  ) : (
    <aside className="replay-entry">
      <button onClick={open}>录制选区讲解</button>
      {error && <span role="status">{error}</span>}
    </aside>
  );
}

export function ReplayLink({ hash }: { hash: string }) {
  const [clip, setClip] = useState<Clip>();
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    loadClip(hash)
      .then((value) => active && setClip(value))
      .catch((e) => active && setError(String(e)));
    return () => {
      active = false;
    };
  }, [hash]);
  return clip ? (
    <Studio snapshot={clip} original={clip} />
  ) : (
    <main role="status">{error || "正在打开讲解…"}</main>
  );
}

function Studio({
  snapshot,
  original,
  close,
}: {
  snapshot: Snapshot;
  original?: Clip;
  close?: () => void;
}) {
  const initial: Frame = {
    time: 0,
    view: [0, 0, snapshot.width, snapshot.height],
    point: null,
  };
  const [frame, setFrame] = useState<Frame>(original?.frames[0] || initial);
  const current = useRef(frame);
  const svg = useRef<SVGSVGElement>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const recorder = useRef<MediaRecorder | undefined>(undefined);
  const started = useRef(0);
  const frames = useRef<Frame[]>([]);
  const drag = useRef<[number, number] | null>(null);
  const [phase, setPhase] = useState("idle");
  const [clip, setClip] = useState(original);
  const [playing, setPlaying] = useState(false);
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const rec = recorder.current;
      if (rec?.state === "recording") {
        rec.stop();
      }
      rec?.stream.getTracks().forEach((track) => track.stop());
    };
  }, []);
  function show(next: Frame) {
    current.current = next;
    setFrame(next);
  }
  function change(next: Frame) {
    next = { ...next, time: performance.now() - started.current };
    show(next);
    if (recorder.current?.state === "recording") {
      frames.current.push(next);
    }
  }
  useEffect(() => {
    if (!playing || !clip || !audio.current || !svg.current) {
      return;
    }
    const win = svg.current.ownerDocument.defaultView!;
    let id: number;
    function tick() {
      if (audio.current) {
        show(frameAt(clip!.frames, audio.current.currentTime * 1000));
      }
      id = win.requestAnimationFrame(tick);
    }
    tick();
    return () => win.cancelAnimationFrame(id);
  }, [playing, clip]);

  async function record() {
    setPhase("pending");
    setError("");
    let stream: MediaStream | undefined;
    try {
      stream =
        await svg.current!.ownerDocument.defaultView!.navigator.mediaDevices.getUserMedia(
          { audio: true },
        );
      if (!mounted.current) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      const rec = new MediaRecorder(stream, { audioBitsPerSecond: 32000 });
      recorder.current = rec;
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = async () => {
        rec.stream.getTracks().forEach((t) => t.stop());
        if (!mounted.current) {
          return;
        }
        try {
          const sound = await dataUrl(new Blob(chunks, { type: rec.mimeType }));
          setClip({
            ...snapshot,
            version: 1,
            frames: frames.current,
            audio: sound,
          });
          show(frames.current[0]);
        } catch (e) {
          setError(String(e));
        }
        setPhase("idle");
      };
      frames.current = [{ ...current.current, time: 0 }];
      started.current = performance.now();
      rec.start();
      setPhase("recording");
    } catch (e) {
      stream?.getTracks().forEach((t) => t.stop());
      if (mounted.current) {
        setError(`无法开始录音：${String(e)}`);
        setPhase("idle");
      }
    }
  }
  async function publish() {
    setPhase("pending");
    setError("");
    try {
      setLink(await shareClip(clip!, svg.current!.ownerDocument.location));
    } catch (e) {
      setError(String(e));
    } finally {
      setPhase("idle");
    }
  }
  function position(x: number, y: number): [number, number] {
    const node = svg.current!;
    const p = node.createSVGPoint();
    p.x = x;
    p.y = y;
    const q = p.matrixTransform(node.getScreenCTM()!.inverse());
    return [q.x, q.y];
  }
  return (
    <section className="replay-studio" aria-label="白板讲解">
      <header>
        <strong>{original ? "白板讲解回放" : "录制选区讲解"}</strong>
        {close && (
          <button disabled={phase !== "idle"} onClick={close}>
            返回白板
          </button>
        )}
      </header>
      <svg
        ref={svg}
        aria-label="评审定稿"
        viewBox={frame.view.join(" ")}
        onPointerDown={(e) => {
          if (!playing) {
            drag.current = [e.clientX, e.clientY];
            e.currentTarget.setPointerCapture(e.pointerId);
          }
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
        onPointerMove={(e) => {
          if (playing) {
            return;
          }
          const p = position(e.clientX, e.clientY);
          const [x, y, w, h] = current.current.view;
          if (drag.current) {
            const old = position(...drag.current);
            drag.current = [e.clientX, e.clientY];
            change({
              ...current.current,
              view: [x + old[0] - p[0], y + old[1] - p[1], w, h],
              point: null,
            });
          } else if (!clip) {
            change({ ...current.current, point: p });
          }
        }}
        onWheel={(e) => {
          if (playing) {
            return;
          }
          const [px, py] = position(e.clientX, e.clientY);
          const [x, y, w, h] = current.current.view;
          const scale = e.deltaY > 0 ? 1.2 : 1 / 1.2;
          if (
            w * scale < snapshot.width / 64 ||
            w * scale > snapshot.width * 4
          ) {
            return;
          }
          change({
            ...current.current,
            view: [
              px + (x - px) * scale,
              py + (y - py) * scale,
              w * scale,
              h * scale,
            ],
          });
        }}
      >
        <image
          href={snapshot.image}
          width={snapshot.width}
          height={snapshot.height}
        />
        {frame.point && (
          <circle
            cx={frame.point[0]}
            cy={frame.point[1]}
            r={frame.view[2] / 140}
            fill="#e53935"
          />
        )}
      </svg>
      <footer>
        {!clip && (
          <button
            disabled={phase === "pending"}
            onClick={() =>
              phase === "recording" ? recorder.current?.stop() : record()
            }
          >
            {phase === "recording" ? "结束录制" : "开始录制"}
          </button>
        )}
        {clip && (
          <audio
            ref={audio}
            src={clip.audio}
            controls
            onPlay={() => {
              show(frameAt(clip.frames, audio.current!.currentTime * 1000));
              setPlaying(true);
            }}
            onPause={() => setPlaying(false)}
            onSeeked={() =>
              show(frameAt(clip.frames, audio.current!.currentTime * 1000))
            }
          />
        )}
        {clip && !original && !link && (
          <button onClick={publish} disabled={phase === "pending"}>
            生成试用链接
          </button>
        )}
        {link && (
          <label>
            持链接者可查看选区与录音{" "}
            <input
              aria-label="试用链接"
              readOnly
              value={link}
              onFocus={(e) => e.target.select()}
            />
          </label>
        )}
        <small>
          {clip
            ? "暂停后拖动或滚轮缩放，继续播放会回到讲解视野。"
            : "移动鼠标指出分支，拖动平移，滚轮缩放。只录制麦克风和此选区。"}
        </small>
        {error && <span role="alert">{error}</span>}
      </footer>
    </section>
  );
}
