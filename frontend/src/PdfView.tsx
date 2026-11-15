import { useEffect, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/TextLayer.css';
import 'react-pdf/dist/Page/AnnotationLayer.css';

pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString();

export default function PdfView({ url, page, onPageCount }: { url: string; page: number; onPageCount?: (count: number) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(360);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(220, entry.contentRect.width)));
    if (container.current) observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  return <div className="pdf-canvas" ref={container}>
    <Document file={url} onLoadSuccess={({numPages}) => onPageCount?.(numPages)} loading={<p className="empty-note">正在打开 PDF 原件…</p>} error={<p className="empty-note">PDF 暂时无法打开，请使用“在新窗口打开原件”。</p>}>
      <Page pageNumber={page} width={width} renderAnnotationLayer={false} />
    </Document>
  </div>;
}
