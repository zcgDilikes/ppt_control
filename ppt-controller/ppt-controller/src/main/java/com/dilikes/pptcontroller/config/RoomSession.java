package com.dilikes.pptcontroller.config;


import jakarta.websocket.Session;

import java.io.IOException;


/**
 * 房间会话实体类
 * 存储每个房间的 小程序端Session + Python被控端Session
 * 用于消息精准转发
 */
public class RoomSession {

    private final String roomId;
    private Session miniSession;   // 小程序端
    private Session pythonSession; // Python控制端

    public RoomSession(String roomId) {
        this.roomId = roomId;
    }

    // 安全关闭所有连接
    public void closeAll() {
        closeSession(miniSession);
        closeSession(pythonSession);
    }

    private void closeSession(Session session) {
        if (session != null && session.isOpen()) {
            try {
                session.close();
            } catch (IOException ignored) {}
        }
    }

    // getter & setter
    public Session getMiniSession() { return miniSession; }
    public void setMiniSession(Session miniSession) { this.miniSession = miniSession; }
    public Session getPythonSession() { return pythonSession; }
    public void setPythonSession(Session pythonSession) { this.pythonSession = pythonSession; }
}
