//
//  TargetEffectsScene.swift
//  Mosquito-finder
//
//  SpriteKit 特效场景 - 酷炫的目标标记效果
//

import SpriteKit
import SwiftUI

/// SpriteKit 特效场景
class TargetEffectsScene: SKScene {
    
    // MARK: - Properties
    
    private var targetNodes: [UUID: SKNode] = [:]
    private var scanLineNode: SKShapeNode?
    
    // MARK: - Setup
    
    override func didMove(to view: SKView) {
        backgroundColor = .clear
        // 扫描线已移除以避免遮挡问题
    }
    
    /// 可选：启用扫描线效果
    func enableScanLine() {
        guard scanLineNode == nil, size.width > 0 else { return }
        
        // 创建扫描线
        let scanLine = SKShapeNode(rectOf: CGSize(width: size.width, height: 2))
        scanLine.fillColor = UIColor.green.withAlphaComponent(0.3)
        scanLine.strokeColor = .clear
        scanLine.position = CGPoint(x: size.width / 2, y: size.height)
        scanLine.zPosition = 100
        scanLine.name = "scanLine"
        addChild(scanLine)
        self.scanLineNode = scanLine
        
        // 扫描线动画
        let moveDown = SKAction.moveTo(y: 0, duration: 2.0)
        let moveUp = SKAction.moveTo(y: size.height, duration: 0)
        let fade = SKAction.sequence([
            SKAction.fadeAlpha(to: 0.5, duration: 1.0),
            SKAction.fadeAlpha(to: 0.2, duration: 1.0)
        ])
        let scanAction = SKAction.repeatForever(SKAction.sequence([moveDown, moveUp]))
        let fadeAction = SKAction.repeatForever(fade)
        
        scanLine.run(SKAction.group([scanAction, fadeAction]))
    }
    
    // MARK: - Public Methods
    
    /// 更新目标显示
    func updateTargets(_ targets: [TrackedTarget]) {
        // 移除不再存在的目标
        let currentIDs = Set(targets.map { $0.id })
        for (id, node) in targetNodes {
            if !currentIDs.contains(id) {
                node.run(SKAction.sequence([
                    SKAction.scale(to: 0, duration: 0.2),
                    SKAction.removeFromParent()
                ]))
                targetNodes.removeValue(forKey: id)
            }
        }
        
        // 添加或更新目标
        for target in targets {
            if let existingNode = targetNodes[target.id] {
                // 更新位置
                let newPosition = CGPoint(x: target.center.x, y: size.height - target.center.y)
                existingNode.run(SKAction.move(to: newPosition, duration: 0.1))
                
                // 更新状态
                updateNodeState(existingNode, state: target.state, size: target.size)
            } else {
                // 创建新节点
                let node = createTargetNode(for: target)
                addChild(node)
                targetNodes[target.id] = node
                
                // 出现动画
                node.setScale(0)
                node.run(SKAction.scale(to: 1.0, duration: 0.3))
            }
        }
    }
    
    // MARK: - Private Methods
    
    private func createTargetNode(for target: TrackedTarget) -> SKNode {
        let container = SKNode()
        container.position = CGPoint(x: target.center.x, y: size.height - target.center.y)
        container.name = target.id.uuidString
        
        let ringSize = max(target.size.width, target.size.height) + 30
        
        // 外层发光环
        let outerRing = createGlowRing(radius: ringSize / 2, color: colorForState(target.state))
        outerRing.name = "outerRing"
        container.addChild(outerRing)
        
        // 内层扫描环
        let innerRing = createScanRing(radius: ringSize / 2 - 8, color: colorForState(target.state))
        innerRing.name = "innerRing"
        container.addChild(innerRing)
        
        // 角标记
        let corners = createCornerMarkers(size: CGSize(width: ringSize, height: ringSize), color: colorForState(target.state))
        corners.name = "corners"
        container.addChild(corners)
        
        // 状态标签
        let label = createStatusLabel(state: target.state)
        label.position = CGPoint(x: 0, y: -ringSize / 2 - 25)
        label.name = "label"
        container.addChild(label)
        
        return container
    }
    
    private func createGlowRing(radius: CGFloat, color: UIColor) -> SKShapeNode {
        let ring = SKShapeNode(circleOfRadius: radius)
        ring.strokeColor = color
        ring.lineWidth = 2
        ring.fillColor = .clear
        ring.glowWidth = 8
        
        // 脉冲动画
        let pulse = SKAction.sequence([
            SKAction.scale(to: 1.1, duration: 0.5),
            SKAction.scale(to: 1.0, duration: 0.5)
        ])
        ring.run(SKAction.repeatForever(pulse))
        
        // 透明度闪烁
        let fade = SKAction.sequence([
            SKAction.fadeAlpha(to: 0.5, duration: 0.3),
            SKAction.fadeAlpha(to: 1.0, duration: 0.3)
        ])
        ring.run(SKAction.repeatForever(fade))
        
        return ring
    }
    
    private func createScanRing(radius: CGFloat, color: UIColor) -> SKShapeNode {
        // 创建弧形扫描效果
        let path = UIBezierPath(arcCenter: .zero, radius: radius, startAngle: 0, endAngle: .pi / 2, clockwise: true)
        let ring = SKShapeNode(path: path.cgPath)
        ring.strokeColor = color.withAlphaComponent(0.8)
        ring.lineWidth = 3
        ring.lineCap = .round
        ring.fillColor = .clear
        
        // 旋转动画
        let rotate = SKAction.rotate(byAngle: .pi * 2, duration: 1.5)
        ring.run(SKAction.repeatForever(rotate))
        
        return ring
    }
    
    private func createCornerMarkers(size: CGSize, color: UIColor) -> SKNode {
        let container = SKNode()
        let cornerLength: CGFloat = 15
        let halfWidth = size.width / 2
        let halfHeight = size.height / 2
        
        let positions = [
            (CGPoint(x: -halfWidth, y: halfHeight), CGFloat.pi / 2),      // 左上
            (CGPoint(x: halfWidth, y: halfHeight), CGFloat.pi),          // 右上
            (CGPoint(x: halfWidth, y: -halfHeight), -CGFloat.pi / 2),    // 右下
            (CGPoint(x: -halfWidth, y: -halfHeight), 0)                  // 左下
        ]
        
        for (position, rotation) in positions {
            let path = UIBezierPath()
            path.move(to: CGPoint(x: 0, y: cornerLength))
            path.addLine(to: .zero)
            path.addLine(to: CGPoint(x: cornerLength, y: 0))
            
            let corner = SKShapeNode(path: path.cgPath)
            corner.strokeColor = color
            corner.lineWidth = 3
            corner.lineCap = .round
            corner.position = position
            corner.zRotation = rotation
            container.addChild(corner)
        }
        
        return container
    }
    
    private func createStatusLabel(state: TargetState) -> SKLabelNode {
        let label = SKLabelNode(fontNamed: "Menlo-Bold")
        label.fontSize = 12
        label.fontColor = colorForState(state)
        label.text = textForState(state)
        label.horizontalAlignmentMode = .center
        
        // 背景
        let bg = SKShapeNode(rectOf: CGSize(width: label.frame.width + 16, height: 20), cornerRadius: 4)
        bg.fillColor = UIColor.black.withAlphaComponent(0.7)
        bg.strokeColor = colorForState(state).withAlphaComponent(0.5)
        bg.lineWidth = 1
        bg.position = CGPoint(x: 0, y: -3)
        bg.zPosition = -1
        label.addChild(bg)
        
        return label
    }
    
    private func updateNodeState(_ node: SKNode, state: TargetState, size: CGSize) {
        let color = colorForState(state)
        
        if let outerRing = node.childNode(withName: "outerRing") as? SKShapeNode {
            outerRing.strokeColor = color
        }
        
        if let innerRing = node.childNode(withName: "innerRing") as? SKShapeNode {
            innerRing.strokeColor = color.withAlphaComponent(0.8)
        }
        
        if let corners = node.childNode(withName: "corners") {
            corners.children.forEach { child in
                if let shape = child as? SKShapeNode {
                    shape.strokeColor = color
                }
            }
        }
        
        if let label = node.childNode(withName: "label") as? SKLabelNode {
            label.text = textForState(state)
            label.fontColor = color
        }
        
        // 确认时添加粒子效果
        if state == .confirmed && node.childNode(withName: "particles") == nil {
            if let particles = createConfirmationParticles(color: color) {
                particles.name = "particles"
                node.addChild(particles)
            }
        }
    }
    
    private func createConfirmationParticles(color: UIColor) -> SKEmitterNode? {
        let emitter = SKEmitterNode()
        emitter.particleTexture = SKTexture(imageNamed: "spark") // 可选
        emitter.particleBirthRate = 30
        emitter.particleLifetime = 1.0
        emitter.particleSpeed = 50
        emitter.particleSpeedRange = 20
        emitter.emissionAngleRange = .pi * 2
        emitter.particleScale = 0.1
        emitter.particleScaleRange = 0.05
        emitter.particleAlpha = 0.8
        emitter.particleAlphaSpeed = -0.8
        emitter.particleColor = color
        emitter.particleColorBlendFactor = 1.0
        emitter.targetNode = self
        return emitter
    }
    
    private func colorForState(_ state: TargetState) -> UIColor {
        switch state {
        case .suspect:
            return UIColor(red: 0.4, green: 1.0, blue: 0.4, alpha: 1.0)  // 绿色
        case .engaging:
            return UIColor(red: 1.0, green: 0.8, blue: 0.2, alpha: 1.0)  // 黄色
        case .confirmed:
            return UIColor(red: 1.0, green: 0.2, blue: 0.2, alpha: 1.0)  // 红色
        case .dismissed:
            return UIColor.gray
        }
    }
    
    private func textForState(_ state: TargetState) -> String {
        switch state {
        case .suspect:
            return "SCANNING"
        case .engaging:
            return "LOCKING"
        case .confirmed:
            return "TARGET!"
        case .dismissed:
            return "CLEAR"
        }
    }
}

// MARK: - SwiftUI Wrapper

struct TargetEffectsView: UIViewRepresentable {
    let targets: [TrackedTarget]
    
    func makeUIView(context: Context) -> SKView {
        let view = SKView()
        
        // 关键：设置透明背景
        view.backgroundColor = .clear
        view.allowsTransparency = true
        view.isOpaque = false
        
        // 禁用不需要的功能以提升性能
        view.showsFPS = false
        view.showsNodeCount = false
        view.ignoresSiblingOrder = true
        
        return view
    }
    
    func updateUIView(_ uiView: SKView, context: Context) {
        // 确保 view 有有效尺寸
        guard uiView.bounds.size.width > 0 && uiView.bounds.size.height > 0 else {
            return
        }
        
        // 获取或创建场景
        if let scene = uiView.scene as? TargetEffectsScene {
            scene.size = uiView.bounds.size
            scene.updateTargets(targets)
        } else {
            // 首次创建场景
            let scene = TargetEffectsScene(size: uiView.bounds.size)
            scene.scaleMode = .resizeFill
            scene.backgroundColor = .clear
            uiView.presentScene(scene)
            scene.updateTargets(targets)
        }
    }
}

