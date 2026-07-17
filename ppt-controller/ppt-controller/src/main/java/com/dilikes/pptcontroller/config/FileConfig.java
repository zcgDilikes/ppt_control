package com.dilikes.pptcontroller.config;

import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import java.io.File;

@Component
public class FileConfig {

    @Value("${file.storage.path}")
    private String basePath;

    @PostConstruct
    public void init() {
        File root = new File(basePath);
        if (!root.exists()) {
            root.mkdirs();
        }
    }

    // 房间专属目录
    public String getRoomDir(String roomId) {
        String path = basePath + "room_" + roomId + "/";
        File dir = new File(path);
        if (!dir.exists()) dir.mkdirs();
        return path;
    }

    public String getBasePath() {
        return basePath;
    }
}
