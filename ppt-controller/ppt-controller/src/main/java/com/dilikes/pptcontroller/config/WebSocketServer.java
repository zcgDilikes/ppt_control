package com.dilikes.pptcontroller.config;

import jakarta.websocket.*;
import jakarta.websocket.server.PathParam;
import jakarta.websocket.server.ServerEndpoint;
import org.springframework.stereotype.Component;


/**
 * WebSocket 服务端
 * 路径：/ws/{clientType}/{roomId}
 * - mini 或 mp：微信小程序 → 记入 miniSession
 * - python：PC 端 ppt_pc_client → 记入 pythonSession（须与小程序不同路径，否则转发失败）
 * 消息在 mini ↔ python 之间互转；FILE_ARRIVED 等由 HTTP 调用 RoomManager.forwardToTarget(roomId, msg) 只推 python。
 */
@Component
@ServerEndpoint("/ws/{clientType}/{roomId}")
public class WebSocketServer {

    /**
     * 连接建立成功调用
     */
    @OnOpen
    public void onOpen(Session session,
                       @PathParam("clientType") String clientType,
                       @PathParam("roomId") String roomId) {
        // 将Session绑定到房间
        RoomManager.addSession(roomId, clientType, session);
    }

    /**
     * 收到客户端消息后调用
     */
    @OnMessage
    public void onMessage(String message,
                          Session session,
                          @PathParam("roomId") String roomId) {
        System.out.println("【收到消息】房间：" + roomId + "，内容：" + message);
        RoomManager.forwardToTarget(roomId, message, session);
    }

    /**
     * 连接关闭调用
     */
    @OnClose
    public void onClose(@PathParam("clientType") String clientType,
                        @PathParam("roomId") String roomId) {
        RoomManager.removeSession(roomId, clientType);
    }

    /**
     * 发生错误时调用
     */
    @OnError
    public void onError(Session session, Throwable error) {
        error.printStackTrace();
    }
}
