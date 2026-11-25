import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./theme.css";
import "./librechat/chat.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode><App tutorPresentation="chat" /></StrictMode>,
);
