"use client";

import { ChangeEvent, DragEvent, useState } from "react";

type Props = {
  material: string;
  onLoad: (text: string) => void;
  onError: (message: string) => void;
};

export default function FileDrop({ material, onLoad, onError }: Props) {
  const [dragging, setDragging] = useState(false);
  const [loadedName, setLoadedName] = useState("");

  async function loadFiles(files: FileList | null) {
    if (!files?.length) return;
    onError("");
    if (files.length !== 1) {
      onError("请一次选择一个文件");
      return;
    }
    const file = files[0];
    if (!/\.(txt|md)$/i.test(file.name) || file.size > 100000) {
      onError("请选择不超过 100 KB 的 TXT 或 Markdown 文件");
      return;
    }
    try {
      const text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      if (text.includes("\u0000") || text.length > 100000) throw new Error();
      if (material && material !== text && !window.confirm("上传文件会替换上方已有的参考资料，是否继续？")) return;
      onLoad(text);
      setLoadedName(file.name);
    } catch {
      onError("文件不是有效的 UTF-8 文字，请检查格式");
    }
  }

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    void loadFiles(event.target.files);
    event.target.value = "";
  }

  function dropFile(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    void loadFiles(event.dataTransfer.files);
  }

  return <>
    <label className={`file-drop${dragging ? " is-dragging" : ""}`} htmlFor="file"
      onDragOver={event => { event.preventDefault(); setDragging(true); }}
      onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
      onDrop={dropFile}>
      <span className="file-drop-title">将文件拖到这里，或点击选择文件</span>
      <span className="file-drop-hint">支持 TXT / Markdown，单个文件不超过 100 KB</span>
      <input id="file" type="file" accept=".txt,.md,text/plain,text/markdown" onChange={selectFile}/>
    </label>
    {loadedName && <p className="file-loaded" role="status">已读取：{loadedName}，内容已填入上方参考资料</p>}
  </>;
}
