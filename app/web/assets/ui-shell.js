import React from "https://esm.sh/react@18.2.0";
import { createRoot } from "https://esm.sh/react-dom@18.2.0/client";
import { flushSync } from "https://esm.sh/react-dom@18.2.0";
import htm from "https://esm.sh/htm@3.1.1";
import {
  Plus,
  Sparkles,
  FilePenLine,
  FileSearch,
  SlidersHorizontal,
  Wrench,
  FolderOpen,
  Database,
} from "https://esm.sh/lucide-react@0.469.0?deps=react@18.2.0";

const html = htm.bind(React.createElement);

function AppShell() {
  return html`
    <div className="h-screen w-screen overflow-hidden bg-canvas text-textMain font-sans">
      <div className="layout">
        <aside className="panel panel-left flex min-h-0 flex-col gap-3 bg-shell px-3 py-3">
          <div className="panel-head flex items-center gap-2 rounded-xl px-2 py-1.5">
            <div className="brand-mark">AR</div>
            <div className="min-w-0">
              <h1 className="truncate text-[0.78rem] font-medium tracking-wide">AR Agent Runtime</h1>
              <p className="truncate text-[0.73rem] text-textSub/80">Frontend Test Console</p>
            </div>
          </div>

          <div className="stack-actions">
            <button id="newSessionBtn" className="btn btn-primary" type="button">
              <span className="inline-flex items-center gap-1.5">
                <${Plus} size=${15} strokeWidth=${2} />
                新建会话
              </span>
            </button>
            <button id="deleteSessionBtn" className="btn btn-danger" type="button">删除当前会话</button>
          </div>

          <div className="card rounded-xl">
            <label className="field-label" htmlFor="sessionIdText">当前 Session</label>
            <div id="sessionIdText" className="mono session-id">(尚未创建)</div>
          </div>

          <div className="card rounded-xl">
            <div className="card-title">快捷测试</div>
            <div className="quick-grid">
              <button className="chip" type="button" data-prompt="请记住我先不用数据库">
                <span className="inline-flex items-center gap-1.5">
                  <${Sparkles} size=${13} strokeWidth=${2} />
                  记忆偏好
                </span>
              </button>
              <button className="chip" type="button" data-prompt="请在 workspace 写一个 hello.txt">
                <span className="inline-flex items-center gap-1.5">
                  <${FilePenLine} size=${13} strokeWidth=${2} />
                  写文件
                </span>
              </button>
              <button className="chip" type="button" data-prompt="请帮我读取 workspace 里的文件">
                <span className="inline-flex items-center gap-1.5">
                  <${FileSearch} size=${13} strokeWidth=${2} />
                  读文件
                </span>
              </button>
            </div>
          </div>

          <div className="card grow rounded-xl">
            <div className="card-title">本地会话历史</div>
            <ul id="sessionList" className="session-list"></ul>
          </div>
        </aside>

        <main className="chat-shell relative min-h-0 bg-canvas">
          <header className="chat-head">
            <div className="chat-head-slot"></div>
            <div className="chat-head-title">Single Agent Runtime</div>
            <div id="healthBadge" className="health-badge health-unknown">连接中...</div>
          </header>

          <section id="thread" className="thread" aria-live="polite"></section>
          <button id="jumpToLatestBtn" className="jump-to-latest" type="button" aria-label="jump to latest">
            回到底部
          </button>

          <form id="composerForm" className="composer" autoComplete="off">
            <div className="composer-left">
              <button
                id="composerUploadBtn"
                type="button"
                className="btn btn-upload-trigger"
                aria-label="上传文件"
                title="上传图片或文件"
                aria-haspopup="menu"
                aria-expanded="false"
              >
                +
              </button>
              <div id="composerUploadMenu" className="composer-upload-menu" role="menu" aria-hidden="true"></div>
            </div>
            <input
              id="composerFileInput"
              type="file"
              hidden
              accept=".pdf,.md,.markdown,.json,.txt,.png,.jpg,.jpeg,.webp"
            />
            <div id="composerInputWrap" className="composer-input-wrap">
              <textarea
                id="messageInput"
                rows="1"
                placeholder="输入消息后回车发送，Shift+Enter 换行；输入 @ 可引用会话文件"
                aria-label="message input"
              ></textarea>
              <div id="mentionMenu" className="mention-menu" role="listbox" aria-hidden="true"></div>
            </div>
            <button id="sendBtn" type="submit" className="btn btn-send">发送</button>
          </form>
        </main>

        <aside className="panel panel-right flex min-h-0 flex-col gap-3 bg-shell px-3 py-3">
          <div className="card rounded-xl">
            <div className="card-title">
              <span className="inline-flex items-center gap-1.5">
                <${SlidersHorizontal} size=${13} strokeWidth=${2} />
                请求参数
              </span>
            </div>
            <label className="field-label">Skills</label>
            <div className="skill-row">
              <label><input type="checkbox" value="base" defaultChecked /> base</label>
              <label><input type="checkbox" value="memory" defaultChecked /> memory</label>
              <label><input type="checkbox" value="memory-editor" defaultChecked /> memory-editor</label>
              <label><input type="checkbox" value="tools" defaultChecked /> tools</label>
            </div>

            <label className="field-label" htmlFor="maxRoundsInput">max_tool_rounds</label>
            <input id="maxRoundsInput" className="number-input" type="number" min="0" max="10" defaultValue="3" />
          </div>

          <div className="card rounded-xl">
            <div className="card-title">
              <span className="inline-flex items-center gap-1.5">
                <${Wrench} size=${13} strokeWidth=${2} />
                调试查询
              </span>
            </div>
            <div className="stack-actions">
              <button id="refreshFilesBtn" className="btn btn-secondary" type="button">刷新 Files</button>
              <button id="refreshEventsBtn" className="btn btn-secondary" type="button">刷新 Events</button>
              <button id="refreshMemoriesBtn" className="btn btn-secondary" type="button">刷新 Memories</button>
            </div>
          </div>

          <div className="card rounded-xl">
            <div className="card-title">
              <span className="inline-flex items-center gap-1.5">
                <${FolderOpen} size=${13} strokeWidth=${2} />
                会话文件
              </span>
            </div>
            <div id="uploadStatusText" className="tiny-text"></div>
            <ul id="sessionFilesList" className="file-list"></ul>
          </div>

          <div className="card grow rounded-xl">
            <div className="card-title">最近工具调用</div>
            <pre id="toolCallsView" className="json-view">[]</pre>
            <div className="card-title spacing">最近 Memory 命中</div>
            <pre id="memoryHitsView" className="json-view">[]</pre>
            <div className="card-title spacing">
              <span className="inline-flex items-center gap-1.5">
                <${Database} size=${13} strokeWidth=${2} />
                Events
              </span>
            </div>
            <pre id="eventsView" className="json-view">[]</pre>
            <div className="card-title spacing">Memories</div>
            <pre id="memoriesView" className="json-view">[]</pre>
          </div>
        </aside>
      </div>
    </div>
  `;
}

const mountNode = document.getElementById("root");
if (mountNode) {
  const root = createRoot(mountNode);
  flushSync(() => {
    root.render(html`<${AppShell} />`);
  });
}
