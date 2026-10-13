// 派生自 kouqiang-beikao/packages/learning-ui/src/reader.tsx；保留安全渲染和选择回滚。
import { useEffect, useState } from "react";
import type { ContentBlock } from "../types";
function text(value: unknown): string {
  if (typeof value === "string") return value;
  if (value && typeof value === "object" && "text" in value)
    return String(value.text);
  return JSON.stringify(value ?? "");
}
export function ContentBlocks({
  blocks,
  imageUrl,
  onImage,
}: {
  blocks: ContentBlock[];
  imageUrl: (path: string) => string;
  onImage?: (src: string, caption: string) => void;
}) {
  return (
    <div className="content-blocks">
      {blocks.map((block, index) => {
        const key = String(block.id ?? "block-" + index);
        const kind = block.type ?? block.kind;
        const imagePath = block.path ?? block.file_id;
        if (kind === "image" && imagePath) {
          const src = imageUrl(imagePath!);
          return (
            <figure key={key} id={key}>
              <button
                className="image-button"
                onClick={() => onImage?.(src, block.caption ?? "原书插图")}
                aria-label={"放大：" + (block.caption ?? "原书插图")}
              >
                <SafeImage
                  src={src}
                  caption={block.caption ?? "原书插图"}
                  width={Number(block.width) || undefined}
                  height={Number(block.height) || undefined}
                />
              </button>
              {block.caption && <figcaption>{block.caption}</figcaption>}
            </figure>
          );
        }
        if (kind === "heading")
          return (
            <h3 key={key} id={key}>
              {block.text}
            </h3>
          );
        if (kind === "table")
          return (
            <div key={key} id={key} className="table-scroll">
              <table>
                {block.headers && (
                  <thead>
                    <tr>
                      {block.headers.map((cell, i) => (
                        <th key={i}>{text(cell)}</th>
                      ))}
                    </tr>
                  </thead>
                )}
                <tbody>
                  {block.rows?.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td key={j}>{text(cell)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        if (kind === "list" && block.items)
          return (
            <ul key={key} id={key}>
              {block.items.map((item, i) => (
                <li key={i}>{text(item)}</li>
              ))}
            </ul>
          );
        if (block.text)
          return (
            <p
              key={key}
              id={key}
              style={
                kind === "list_item"
                  ? { paddingLeft: Math.min(Number(block.level ?? 1), 5) * 12 }
                  : undefined
              }
            >
              {block.marker && <span>{block.marker} </span>}
              {block.text}
            </p>
          );
        if (Array.isArray(block.blocks))
          return (
            <ContentBlocks
              key={key}
              blocks={block.blocks as ContentBlock[]}
              imageUrl={imageUrl}
              onImage={onImage}
            />
          );
        return (
          <pre key={key} id={key}>
            {text(block)}
          </pre>
        );
      })}
    </div>
  );
}
function SafeImage({
  src,
  caption,
  width,
  height,
}: {
  src: string;
  caption: string;
  width?: number;
  height?: number;
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  if (!src) return <span role="status">图片加载中…</span>;
  return failed ? (
    <span className="error">图片缺失：{caption}</span>
  ) : (
    <img
      src={src}
      alt={caption}
      width={width}
      height={height}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}
export function ChoiceOptions({
  options,
  selected,
  disabled,
  onSelect,
  multiple = false,
}: {
  options: Record<string, string>;
  selected: string[];
  disabled?: boolean;
  onSelect: (selected: string[]) => Promise<void> | void;
  multiple?: boolean;
}) {
  const [visual, setVisual] = useState(selected);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(
    () => setVisual(selected),
    [selected.join("|"), Object.keys(options).join("|")],
  );
  async function choose(id: string) {
    const next = multiple
      ? visual.includes(id)
        ? visual.filter((x) => x !== id)
        : [...visual, id]
      : [id];
    setVisual(next);
    setSaving(true);
    setError("");
    try {
      await onSelect(next);
    } catch (e) {
      setVisual(selected);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }
  return (
    <>
      <fieldset className="options" disabled={disabled || saving}>
        <legend className="sr-only">请选择答案</legend>
        {Object.entries(options).map(([id, label], index) => (
          <label key={id} className={visual.includes(id) ? "selected" : ""}>
            <input
              type={multiple ? "checkbox" : "radio"}
              name="answer"
              checked={visual.includes(id)}
              onChange={() => void choose(id)}
            />
            <span className="option-letter">
              {String.fromCharCode(65 + index)}
            </span>
            <span>{label}</span>
          </label>
        ))}
      </fieldset>
      {error && (
        <p role="alert" className="error">
          保存选择失败：{error}
        </p>
      )}
    </>
  );
}
