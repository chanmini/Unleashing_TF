from __future__ import division
import os
import time
from glob import glob
import tensorflow as tf
import numpy as np
import preprocess as pr
import sys

from ops import *
from utils import *

class pix2pix(object):
    def __init__(self, sess, image_size=1024,
                 batch_size=1, sample_size=1, output_size=1024,
                 gf_dim=64, df_dim=64, L1_lambda=100, L2_lambda=0, GAN_lambda=1,
                 input_c_dim=1, output_c_dim=1, dataset_name='bolbbalgan4',
                 checkpoint_dir=None, sample_dir=None, test_dir=None, tagfile_path=None, 
                 logdir=None, d_sche=None, g_sche=None):
        """

        Args:
            sess: TensorFlow session
            batch_size: The size of batch. Should be specified before training.
            output_size: (optional) The resolution in pixels of the images. [256]
            gf_dim: (optional) Dimension of gen filters in first conv layer. [64]
            df_dim: (optional) Dimension of discrim filters in first conv layer. [64]
            input_c_dim: (optional) Dimension of input image color. For grayscale input, set to 1. [3]
            output_c_dim: (optional) Dimension of output image color. For grayscale input, set to 1. [3]
        """
        self.d_sche=d_sche
        self.g_sche=g_sche

        self.sess = sess
        self.is_grayscale = (input_c_dim == 1)
        self.batch_size = batch_size
        self.image_size = image_size
        self.sample_size = sample_size
        self.output_size = output_size

        self.gf_dim = gf_dim
        self.df_dim = df_dim

        self.input_c_dim = input_c_dim
        self.output_c_dim = output_c_dim

        # batch normalization : deals with poor initialization helps gradient flow
        self.d_bn1 = batch_norm(name='d_bn1')
        self.d_bn2 = batch_norm(name='d_bn2')
        self.d_bn3 = batch_norm(name='d_bn3')

        self.g_bn_e2 = batch_norm(name='g_bn_e2')
        self.g_bn_e3 = batch_norm(name='g_bn_e3')
        self.g_bn_e4 = batch_norm(name='g_bn_e4')
        self.g_bn_e5 = batch_norm(name='g_bn_e5')
        self.g_bn_e6 = batch_norm(name='g_bn_e6')
        self.g_bn_e7 = batch_norm(name='g_bn_e7')
        self.g_bn_e8 = batch_norm(name='g_bn_e8')
        self.g_bn_e9 = batch_norm(name='g_bn_e9')

        self.g_bn_d0 = batch_norm(name='g_bn_d0')
        self.g_bn_d1 = batch_norm(name='g_bn_d1')
        self.g_bn_d2 = batch_norm(name='g_bn_d2')
        self.g_bn_d3 = batch_norm(name='g_bn_d3')
        self.g_bn_d4 = batch_norm(name='g_bn_d4')
        self.g_bn_d5 = batch_norm(name='g_bn_d5')
        self.g_bn_d6 = batch_norm(name='g_bn_d6')
        self.g_bn_d7 = batch_norm(name='g_bn_d7')

        
        self.L1_lambda = L1_lambda
        self.L2_lambda = L2_lambda
        self.GAN_lambda = GAN_lambda        
        
        self.tagfile_path=tagfile_path

        self.dataset_name=dataset_name
        self.sample_dir=sample_dir
        self.checkpoint_dir=checkpoint_dir
        self.test_dir=test_dir
        self.logdir=logdir  

        #those part shouldve been at main.py rather than here but im lazy so just go
        self.build_model()


    def build_model(self):
        self.real_data = tf.placeholder(tf.float32,
                                        [self.batch_size, self.image_size, self.image_size,
                                         self.input_c_dim + self.output_c_dim],
                                        name='real_A_and_B_images')

        self.real_A = self.real_data[:, :, :, :self.input_c_dim]
        self.real_B = self.real_data[:, :, :, self.input_c_dim:self.input_c_dim + self.output_c_dim]

        self.fake_B = self.generator(self.real_A)

        self.real_AB = tf.concat([self.real_A, self.real_B], 3)         # concats again with axis=3 which corresponds to axis 2 for preprocess.py (color channel)
        self.fake_AB = tf.concat([self.real_A, self.fake_B], 3)
        self.D, self.D_logits = self.discriminator(self.real_AB, reuse=False)
        self.D_, self.D_logits_ = self.discriminator(self.fake_AB, reuse=True)

        self.fake_B_sample = self.sampler(self.real_A)

        self.d_sum = tf.summary.histogram("d", self.D)
        self.d__sum = tf.summary.histogram("d_", self.D_)
        self.fake_B_sum = tf.summary.image("fake_B", self.fake_B)

        self.d_loss_real = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits, labels=tf.ones_like(self.D)))
        self.d_loss_fake = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits_, labels=tf.zeros_like(self.D_)))
        self.g_loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits_, labels=tf.ones_like(self.D_))) \
                        + self.L1_lambda * tf.reduce_mean(tf.abs(self.real_B - self.fake_B)) \
                        + self.L2_lambda * tf.reduce_mean(tf.pow(self.real_B - self.fake_B, 2))

        self.d_loss_real_sum = tf.summary.scalar("d_loss_real", self.d_loss_real)
        self.d_loss_fake_sum = tf.summary.scalar("d_loss_fake", self.d_loss_fake)

        self.d_loss = self.d_loss_real + self.d_loss_fake

        self.g_loss_sum = tf.summary.scalar("g_loss", self.g_loss)
        self.d_loss_sum = tf.summary.scalar("d_loss", self.d_loss)

        t_vars = tf.trainable_variables()

        self.d_vars = [var for var in t_vars if 'd_' in var.name]
        self.g_vars = [var for var in t_vars if 'g_' in var.name]

        self.saver = tf.train.Saver()


    #treating same as rgb will be okay (since preprocess.py has to deat with dimensions on color channel) 
    def load_random_samples(self):
        data = np.random.choice(glob('./{}/*.npy'.format(self.dataset_name)), self.batch_size)
        sample = [load_npy(sample_file) for sample_file in data]
        sample_images = np.array(sample).astype(np.float32)
        return sample_images


    def sample_model(self, sample_dir, epoch, idx):
        sample_images = self.load_random_samples()

        voice_only= sample_images[:,:,:,:self.input_c_dim]
        ensemble_real=sample_images[:,:,:,self.input_c_dim:]
        ensemble_fake, d_loss, g_loss = self.sess.run(
            [self.fake_B_sample, self.d_loss, self.g_loss],
            feed_dict={self.real_data: sample_images}
            )

        #not sure sampling occurs correctly
        voice_only=np.reshape(voice_only,(1024,1024))
        ensemble_real=np.reshape(ensemble_real, (1024,1024))
        ensemble_fake=np.reshape(ensemble_fake,(1024,1024)) #np.reshape() returns array ndarray.resize() returns NONE 
        
        #if I wanted non-scaled specgram
        #concat=np.concatenate((voice_only, ensemble_real, ensemble_fake), axis=1)#resulting need to be 1024,3072
        #pr.write_specgram_img()

        # scale ensemble_fake
        max_samples=max(np.absolute(ensemble_fake.flatten("C")))
        max_voice=max(np.absolute(voice_only.flatten("C")))
        ensemble_fake_scaled=ensemble_fake*(max_voice/max_samples)
        # save ensemble_fake as nparray np.load("f.npy will load nparray")
        with open(sample_dir+"/fake_ensemble{a}.npy".format(a=idx), "wb") as f:
            np.save(f,ensemble_fake_scaled)
        
        # write specgram (bot: voice, mid: ensemble_real, top: ensemble_fake)
        normalconcat=np.concatenate((voice_only, ensemble_real, ensemble_fake_scaled), axis=1)
        pr.write_specgram_img(normalconcat, '{}/train_{:02d}_{:06d}.png'.format(sample_dir, epoch, idx))
        print("[Sample] d_loss: {:.8f}, g_loss: {:.8f}".format(d_loss, g_loss))


    def train(self, args):
        """Train pix2pix"""
        d_optim = tf.train.AdamOptimizer(args.lr, beta1=args.beta1) \
                          .minimize(self.d_loss, var_list=self.d_vars)
        g_optim = tf.train.AdamOptimizer(args.lr, beta1=args.beta1) \
                          .minimize(self.g_loss, var_list=self.g_vars)

        init_op = tf.global_variables_initializer()
        self.sess.run(init_op)

        self.g_sum = tf.summary.merge([self.d__sum,
            self.fake_B_sum, self.d_loss_fake_sum, self.g_loss_sum])
        self.d_sum = tf.summary.merge([self.d_sum, self.d_loss_real_sum, self.d_loss_sum])
        self.writer = tf.summary.FileWriter(self.logdir, self.sess.graph)

        counter = 1
        start_time = time.time()

        if self.load(self.checkpoint_dir):
            print(" [*] Load SUCCESS")
        else:
            print(" [!] Load failed...")

        for epoch in range(args.epoch):
            data = glob("./{dataset}/*.npy".format(dataset=self.dataset_name))
            np.random.shuffle(data)
            batch_idxs = min(len(data), args.train_size) // self.batch_size

            for idx in range(0, batch_idxs):
                batch_files = data[idx*self.batch_size:(idx+1)*self.batch_size]
                batch = [load_npy(batch_file) for batch_file in batch_files]
                #print("batch_file:\t{a}".format(a=batch[0].shape))
                #print("batch:\t{b}".format(b=np.array(batch).shape))
                batch_images = np.array(batch).astype(np.float32)

                for d_schedule in range(self.d_sche):
                    _, summary_str = self.sess.run([d_optim, self.d_sum],
                                                   feed_dict={ self.real_data: batch_images })
                    self.writer.add_summary(summary_str, counter)

                for g_schedule in range(self.g_sche):
                    _, summary_str = self.sess.run([g_optim, self.g_sum],
                                                   feed_dict={ self.real_data: batch_images })
                    self.writer.add_summary(summary_str, counter)


                errD_fake = self.d_loss_fake.eval({self.real_data: batch_images})
                errD_real = self.d_loss_real.eval({self.real_data: batch_images})
                errG = self.g_loss.eval({self.real_data: batch_images})

                counter += 1
                print("Epoch: [%2d] [%4d/%4d] time: %4.4f, d_loss: %.8f, g_loss: %.8f" \
                    % (epoch, idx, batch_idxs,
                        time.time() - start_time, errD_fake+errD_real, errG))

                
                #if np.mod(counter, 2) == 1:
                if counter in range(40) and np.mod(counter,5)=0:
                    self.sample_model(self.sample_dir, epoch, idx)
                    self.save(self.checkpoint_dir, counter)
                if np.mod(counter, 100) == 1:
                    self.sample_model(self.sample_dir, epoch, idx)
                    #sys.exit("sampling test")

                if np.mod(counter, 500) == 2:
                    self.save(self.checkpoint_dir, counter)

    def discriminator(self, image, y=None, reuse=False):

        with tf.variable_scope("discriminator") as scope:

            # image is 256 x 256 x (input_c_dim + output_c_dim)
            if reuse:
                tf.get_variable_scope().reuse_variables()
            else:
                assert tf.get_variable_scope().reuse == False

            h0 = lrelu(conv2d(image, self.df_dim, name='d_h0_conv'))
            # h0 is (128 x 128 x self.df_dim)
            h1 = lrelu(self.d_bn1(conv2d(h0, self.df_dim*2, name='d_h1_conv')))
            # h1 is (64 x 64 x self.df_dim*2)
            h2 = lrelu(self.d_bn2(conv2d(h1, self.df_dim*4, name='d_h2_conv')))
            # h2 is (32x 32 x self.df_dim*4)
            h3 = lrelu(self.d_bn3(conv2d(h2, self.df_dim*8, d_h=1, d_w=1, name='d_h3_conv')))
            # h3 is (16 x 16 x self.df_dim*8)
            h4 = linear(tf.reshape(h3, [self.batch_size, -1]), 1, 'd_h3_lin')

            return tf.nn.sigmoid(h4), h4
            #linear should retrieve weight so linear(scope or "Linear") in ops.py may tell sth



    def generator(self, image, y=None):
        with tf.variable_scope("generator") as scope:

            s = self.output_size
            s2, s4, s8, s16, s32, s64, s128, s256 = int(s/2), int(s/4), int(s/8), int(s/16), int(s/32), int(s/64), int(s/128), int(s/256)

            # all the sizes are 4 times larger (2 x 2 --> 8 x 8)
            # image is (1024 x 1024 x input_c_dim)
            e1 = conv2d(image, self.gf_dim, name='g_e1_conv')
            # e1 is (512 x 512 x self.gf_dim)
            e2 = self.g_bn_e2(conv2d(lrelu(e1), self.gf_dim*2, name='g_e2_conv'))
            # e2 is (256 x 256 x self.gf_dim*2)
            e3 = self.g_bn_e3(conv2d(lrelu(e2), self.gf_dim*4, name='g_e3_conv'))
            # e3 is (128 x 128 x self.gf_dim*4)
            e4 = self.g_bn_e4(conv2d(lrelu(e3), self.gf_dim*8, name='g_e4_conv'))
            # e4 is (64 x 64 x self.gf_dim*8)
            e5 = self.g_bn_e5(conv2d(lrelu(e4), self.gf_dim*8, name='g_e5_conv'))
            # e5 is (32 x 32 x self.gf_dim*8)
            e6 = self.g_bn_e6(conv2d(lrelu(e5), self.gf_dim*8, name='g_e6_conv'))
            # e6 is (16 x 16 x self.gf_dim*8)
            e7 = self.g_bn_e7(conv2d(lrelu(e6), self.gf_dim*8, name='g_e7_conv'))
            # e7 is (8 x 8 x self.gf_dim*8)
            e8 = self.g_bn_e8(conv2d(lrelu(e7), self.gf_dim*8, name='g_e8_conv'))
            # e8 is (4 x 4 x self.gf_dim*8)
            e9 = self.g_bn_e9(conv2d(lrelu(e8), self.gf_dim*8, name='g_e9_conv'))
            # e9 is (2 x 2 x self.gf_dim*8)

            
            self.d0, self.d0_w, self.d0_b = deconv2d(tf.nn.relu(e9),
                [self.batch_size, s256, s256, self.gf_dim*8], name='g_d0', with_w=True)
            d0 = tf.nn.dropout(self.g_bn_d0(self.d0), 0.5)
            d0 = tf.concat([d0, e8], 3)
            # d1 is (4 x 4 x self.gf_dim*8*2)

            self.d1, self.d1_w, self.d1_b = deconv2d(tf.nn.relu(e8),
                [self.batch_size, s128, s128, self.gf_dim*8], name='g_d1', with_w=True)
            d1 = tf.nn.dropout(self.g_bn_d1(self.d1), 0.5)
            d1 = tf.concat([d1, e7], 3)
            # d1 is (8 x 8 x self.gf_dim*8*2)

            self.d2, self.d2_w, self.d2_b = deconv2d(tf.nn.relu(d1),
                [self.batch_size, s64, s64, self.gf_dim*8], name='g_d2', with_w=True)
            d2 = tf.nn.dropout(self.g_bn_d2(self.d2), 0.5)
            d2 = tf.concat([d2, e6], 3)
            # d2 is (16 x 16 x self.gf_dim*8*2)

            self.d3, self.d3_w, self.d3_b = deconv2d(tf.nn.relu(d2),
                [self.batch_size, s32, s32, self.gf_dim*8], name='g_d3', with_w=True)
            d3 = tf.nn.dropout(self.g_bn_d3(self.d3), 0.5)
            d3 = tf.concat([d3, e5], 3)
            # d3 is (32 x 32 x self.gf_dim*8*2)

            self.d4, self.d4_w, self.d4_b = deconv2d(tf.nn.relu(d3),
                [self.batch_size, s16, s16, self.gf_dim*8], name='g_d4', with_w=True)
            d4 = self.g_bn_d4(self.d4)
            d4 = tf.concat([d4, e4], 3)    #Unet structure: skip connection
            # d4 is (64 x 64 x self.gf_dim*8*2)

            self.d5, self.d5_w, self.d5_b = deconv2d(tf.nn.relu(d4),
                [self.batch_size, s8, s8, self.gf_dim*4], name='g_d5', with_w=True)
            d5 = self.g_bn_d5(self.d5)
            d5 = tf.concat([d5, e3], 3)
            # d5 is (128 x 128 x self.gf_dim*4*2)

            self.d6, self.d6_w, self.d6_b = deconv2d(tf.nn.relu(d5),
                [self.batch_size, s4, s4, self.gf_dim*2], name='g_d6', with_w=True)
            d6 = self.g_bn_d6(self.d6)
            d6 = tf.concat([d6, e2], 3)
            # d6 is (256 x 256 x self.gf_dim*2*2)

            self.d7, self.d7_w, self.d7_b = deconv2d(tf.nn.relu(d6),
                [self.batch_size, s2, s2, self.gf_dim], name='g_d7', with_w=True)
            d7 = self.g_bn_d7(self.d7)
            d7 = tf.concat([d7, e1], 3)
            # d7 is (512 x 512 x self.gf_dim*1*2)

            self.d8, self.d8_w, self.d8_b = deconv2d(tf.nn.relu(d7),
                [self.batch_size, s, s, self.output_c_dim], name='g_d8', with_w=True)
            # d8 is (1024 x 1024 x output_c_dim)

            return tf.nn.tanh(self.d8)

    def sampler(self, image, y=None):

        with tf.variable_scope("generator") as scope:
            scope.reuse_variables()

            s = self.output_size
            s2, s4, s8, s16, s32, s64, s128, s256 = int(s/2), int(s/4), int(s/8), int(s/16), int(s/32), int(s/64), int(s/128), int(s/256)

            # all the sizes are 4 times larger (2 x 2 --> 8 x 8)
            # image is (1024 x 1024 x input_c_dim)
            e1 = conv2d(image, self.gf_dim, name='g_e1_conv')
            # e1 is (512 x 512 x self.gf_dim)
            e2 = self.g_bn_e2(conv2d(lrelu(e1), self.gf_dim*2, name='g_e2_conv'))
            # e2 is (256 x 256 x self.gf_dim*2)
            e3 = self.g_bn_e3(conv2d(lrelu(e2), self.gf_dim*4, name='g_e3_conv'))
            # e3 is (128 x 128 x self.gf_dim*4)
            e4 = self.g_bn_e4(conv2d(lrelu(e3), self.gf_dim*8, name='g_e4_conv'))
            # e4 is (64 x 64 x self.gf_dim*8)
            e5 = self.g_bn_e5(conv2d(lrelu(e4), self.gf_dim*8, name='g_e5_conv'))
            # e5 is (32 x 32 x self.gf_dim*8)
            e6 = self.g_bn_e6(conv2d(lrelu(e5), self.gf_dim*8, name='g_e6_conv'))
            # e6 is (16 x 16 x self.gf_dim*8)
            e7 = self.g_bn_e7(conv2d(lrelu(e6), self.gf_dim*8, name='g_e7_conv'))
            # e7 is (8 x 8 x self.gf_dim*8)
            e8 = self.g_bn_e8(conv2d(lrelu(e7), self.gf_dim*8, name='g_e8_conv'))
            # e8 is (4 x 4 x self.gf_dim*8)
            e9 = self.g_bn_e9(conv2d(lrelu(e8), self.gf_dim*8, name='g_e9_conv'))
            # e9 is (2 x 2 x self.gf_dim*8)


            self.d0, self.d0_w, self.d0_b = deconv2d(tf.nn.relu(e9),
                [self.batch_size, s256, s256, self.gf_dim*8], name='g_d0', with_w=True)
            d0 = tf.nn.dropout(self.g_bn_d0(self.d0), 0.5)
            d0 = tf.concat([d0, e8], 3)
            # d1 is (4 x 4 x self.gf_dim*8*2)

            self.d1, self.d1_w, self.d1_b = deconv2d(tf.nn.relu(e8),
                [self.batch_size, s128, s128, self.gf_dim*8], name='g_d1', with_w=True)
            d1 = tf.nn.dropout(self.g_bn_d1(self.d1), 0.5)
            d1 = tf.concat([d1, e7], 3)
            # d1 is (8 x 8 x self.gf_dim*8*2)

            self.d2, self.d2_w, self.d2_b = deconv2d(tf.nn.relu(d1),
                [self.batch_size, s64, s64, self.gf_dim*8], name='g_d2', with_w=True)
            d2 = tf.nn.dropout(self.g_bn_d2(self.d2), 0.5)
            d2 = tf.concat([d2, e6], 3)
            # d2 is (16 x 16 x self.gf_dim*8*2)

            self.d3, self.d3_w, self.d3_b = deconv2d(tf.nn.relu(d2),
                [self.batch_size, s32, s32, self.gf_dim*8], name='g_d3', with_w=True)
            d3 = tf.nn.dropout(self.g_bn_d3(self.d3), 0.5)
            d3 = tf.concat([d3, e5], 3)
            # d3 is (32 x 32 x self.gf_dim*8*2)

            self.d4, self.d4_w, self.d4_b = deconv2d(tf.nn.relu(d3),
                [self.batch_size, s16, s16, self.gf_dim*8], name='g_d4', with_w=True)
            d4 = self.g_bn_d4(self.d4)
            d4 = tf.concat([d4, e4], 3)    #Unet structure: skip connection
            # d4 is (64 x 64 x self.gf_dim*8*2)

            self.d5, self.d5_w, self.d5_b = deconv2d(tf.nn.relu(d4),
                [self.batch_size, s8, s8, self.gf_dim*4], name='g_d5', with_w=True)
            d5 = self.g_bn_d5(self.d5)
            d5 = tf.concat([d5, e3], 3)
            # d5 is (128 x 128 x self.gf_dim*4*2)

            self.d6, self.d6_w, self.d6_b = deconv2d(tf.nn.relu(d5),
                [self.batch_size, s4, s4, self.gf_dim*2], name='g_d6', with_w=True)
            d6 = self.g_bn_d6(self.d6)
            d6 = tf.concat([d6, e2], 3)
            # d6 is (256 x 256 x self.gf_dim*2*2)

            self.d7, self.d7_w, self.d7_b = deconv2d(tf.nn.relu(d6),
                [self.batch_size, s2, s2, self.gf_dim], name='g_d7', with_w=True)
            d7 = self.g_bn_d7(self.d7)
            d7 = tf.concat([d7, e1], 3)
            # d7 is (512 x 512 x self.gf_dim*1*2)

            self.d8, self.d8_w, self.d8_b = deconv2d(tf.nn.relu(d7),
                [self.batch_size, s, s, self.output_c_dim], name='g_d8', with_w=True)
            # d8 is (1024 x 1024 x output_c_dim)

            return tf.nn.tanh(self.d8)


    def save(self, checkpoint_dir, step):
        model_name = "pix2pix{step}.model".format(step=step)
        self.saver.save(self.sess,
                        os.path.join(checkpoint_dir, model_name),
                        global_step=step)

        #model_dir = self.model_hyp_param
        #checkpoint_dir = os.path.join(checkpoint_dir, model_dir)
        #if not os.path.exists(checkpoint_dir):
        #    os.makedirs(checkpoint_dir)


    def load(self, checkpoint_dir):
        print(" [*] Reading checkpoint...")

        ckpt = tf.train.get_checkpoint_state(checkpoint_dir)
        if ckpt and ckpt.model_checkpoint_path:
            ckpt_name = os.path.basename(ckpt.model_checkpoint_path)  #basename truncates to return filename or name of trailing directory (e.g. basename("asd/as.txt")==as.txt)
            self.saver.restore(self.sess, os.path.join(checkpoint_dir, ckpt_name))
            return True
        else:
            return False

        #model_dir = self.model_hyp_param
        #checkpoint_dir = os.path.join(checkpoint_dir, model_dir)


    def test(self, args):
        """Test pix2pix"""
        init_op = tf.global_variables_initializer()
        self.sess.run(init_op)

        sample_files = glob('{}/*.npy'.format(self.test_dir)) #glob.glob() provides extended support for unix filename like *.txt

        # sort testing input
        n = [int(i) for i in map(lambda x: x.split('/')[-1].split('.npy')[0], sample_files)] #map(function, iterable) w/o for stmt, it can returns func(iterable elements) in list type
        sample_files = [x for (y, x) in sorted(zip(n, sample_files))] #list(zip([1,2,3,4], "abcde")) == [(1,a),(2,b),(3,c),(4,d)] 
                                                                      #zip(*zip(list1,list2))=x,y --> (list(x)==list1, list(y)==list2) is same as (True, True)
        
        # load testing input
        print("Loading testing images ...")
        sample = [load_npy(sample_file, is_test=True) for sample_file in sample_files]
        sample_images = np.array(sample).astype(np.float32)

        sample_images = [sample_images[i:i+self.batch_size]
                         for i in range(0, len(sample_images), self.batch_size)]
        sample_images = np.array(sample_images)
        print(sample_images.shape)

        start_time = time.time()
        if self.load(self.checkpoint_dir):
            print(" [*] Load SUCCESS")
        else:
            print(" [!] Load failed...")

        for i, sample_image in enumerate(sample_images):
            idx = i+1
            print("sampling image ", idx)
            samples = self.sess.run(
                self.fake_B_sample,
                feed_dict={self.real_data: sample_image}
            )
            save_images(samples, [self.batch_size, 1],
                        './{}/test_{:04d}.png'.format(args.test_dir, idx))
            
            recover_audio(pathandwavname='./{}/test_{:04d}.wav'.format(args.test_dir, idx), specgram=sample_image)
            #pr.write_specgram_img(specgram=sample_image, imgname='./{}/test_{:04d}.png'.format(args.test_dir, idx))
