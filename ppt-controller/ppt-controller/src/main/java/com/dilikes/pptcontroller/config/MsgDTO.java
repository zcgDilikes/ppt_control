package com.dilikes.pptcontroller.config;

import com.fasterxml.jackson.annotation.JsonProperty;

public class MsgDTO {

    @JsonProperty("roomId")
    private String roomId;
    @JsonProperty("cmd")
    private String cmd;
    @JsonProperty("x")
    private Double x;
    @JsonProperty("y")
    private Double y;
    @JsonProperty("msg")
    private String msg;

    public String getRoomId() {
        return roomId;
    }

    public void setRoomId(String roomId) {
        this.roomId = roomId;
    }

    public String getCmd() {
        return cmd;
    }

    public void setCmd(String cmd) {
        this.cmd = cmd;
    }

    public Double getX() {
        return x;
    }

    public void setX(Double x) {
        this.x = x;
    }

    public Double getY() {
        return y;
    }

    public void setY(Double y) {
        this.y = y;
    }

    public String getMsg() {
        return msg;
    }

    public void setMsg(String msg) {
        this.msg = msg;
    }
}
