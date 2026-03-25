export default function CodeBlock({ language, code, context }: { language: string; code: string; context?: string }) {
  return (
    <div className="my-3">
      {context && <p className="text-xs text-gray-500 mb-1">{context}</p>}
      <div className="relative">
        <span className="absolute top-2 right-2 text-xs text-gray-400">{language}</span>
        <pre className="p-4 bg-gray-900 text-gray-100 rounded-lg text-sm overflow-x-auto">
          <code>{code}</code>
        </pre>
      </div>
    </div>
  );
}
