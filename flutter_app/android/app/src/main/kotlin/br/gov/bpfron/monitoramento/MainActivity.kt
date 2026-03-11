package br.gov.bpfron.monitoramento

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity

class MainActivity : FlutterActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ensureNotificationChannels()
    }

    private fun ensureNotificationChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val defaultSound = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
        val audioAttr = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_NOTIFICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()

        // Canal: Alertas Críticos
        if (nm.getNotificationChannel("critical_alerts") == null) {
            val ch = NotificationChannel(
                "critical_alerts",
                "Alertas Críticos",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Notificações de detecção de veículos monitorados"
                enableVibration(true)
                setSound(defaultSound, audioAttr)
            }
            nm.createNotificationChannel(ch)
        }

        // Canal: Alarmes Críticos v2
        if (nm.getNotificationChannel("alarm_high_importance_v2") == null) {
            val ch = NotificationChannel(
                "alarm_high_importance_v2",
                "Alarmes Críticos",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Notificações de alarmes críticos com som e vibração"
                enableVibration(true)
                setSound(defaultSound, audioAttr)
            }
            nm.createNotificationChannel(ch)
        }

        // Canal: Alertas Comuns
        if (nm.getNotificationChannel("normal_alerts") == null) {
            val ch = NotificationChannel(
                "normal_alerts",
                "Alertas Comuns",
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply {
                description = "Notificações gerais do aplicativo"
                enableVibration(true)
                setSound(defaultSound, audioAttr)
            }
            nm.createNotificationChannel(ch)
        }
    }
}
